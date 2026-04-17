"""
app/services/estudiante_service.py
Lógica de negocio para alumnos: vinculación y sincronización.
"""
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CodigoVinculacion, Estudiante, EventoAprendizaje
from app.schemas.schemas import (
    SincronizarRequest,
    SincronizarResponse,
    VincularRequest,
    VincularResponse,
)

settings = get_settings()


class EstudianteService:

    async def vincular(
        self, db: AsyncSession, payload: VincularRequest
    ) -> VincularResponse:
        """
        Vincula UUID del dispositivo con un grupo vía código LUDUXX.
        Valida: código existe + no expiró + no fue usado.
        """
        ahora = datetime.now(timezone.utc)
        codigo = await db.get(CodigoVinculacion, payload.codigo_vinculacion)

        if not codigo:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Código de vinculación inválido o expirado.",
            )

        expira = codigo.expira_el
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)

        if codigo.esta_usado or expira < ahora:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Código de vinculación inválido o expirado.",
            )

        # Crear perfil si es primera vez
        estudiante = await db.get(Estudiante, payload.uuid_estudiante)
        if not estudiante:
            total = await db.scalar(
                select(func.count(Estudiante.uuid_estudiante))
                .where(Estudiante.id_grupo == codigo.id_grupo)
            )
            alias = f"Alumno {(total or 0) + 1}"
            estudiante = Estudiante(
                uuid_estudiante=payload.uuid_estudiante,
                id_grupo=codigo.id_grupo,
                alias_estudiante=alias,
            )
            db.add(estudiante)

        codigo.esta_usado = True

        return VincularResponse(
            mensaje="Dispositivo vinculado con éxito.",
            id_grupo=codigo.id_grupo,
        )

    async def sincronizar(
        self, db: AsyncSession, payload: SincronizarRequest
    ) -> SincronizarResponse:
        """
        Volcado de eventos offline.
        Idempotencia: id_evento es PK en SQLite — duplicados rechazados
        automáticamente con IntegrityError, contados como ignorados.
        """
        estudiante = await db.get(Estudiante, payload.uuid_estudiante)
        if not estudiante:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El dispositivo no está vinculado a ningún grupo.",
            )

        procesados = 0
        duplicados = 0
        monedas_nuevas = 0

        for evento in payload.eventos:
            nuevo = EventoAprendizaje(
                id_evento=evento.id_evento,
                uuid_estudiante=payload.uuid_estudiante,
                id_mision=evento.id_mision,
                errores=evento.errores,
                segundos_jugados=evento.segundos_jugados,
                monedas_ganadas=evento.monedas_ganadas,
                fecha_dispositivo=evento.fecha_dispositivo,
            )
            db.add(nuevo)
            try:
                await db.flush()
                procesados += 1
                monedas_nuevas += evento.monedas_ganadas
            except IntegrityError:
                await db.rollback()
                duplicados += 1

        if monedas_nuevas > 0:
            estudiante.monedas_totales += monedas_nuevas

        return SincronizarResponse(
            estado="exito",
            eventos_procesados=procesados,
            duplicados_ignorados=duplicados,
        )


def generar_codigo_ludu() -> str:
    """
    Código de 6 chars con prefijo LUDU.
    Excluye O, 0, I, 1 para evitar confusión al dictarlo.
    """
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    sufijo = "".join(random.choices(chars, k=2))
    return f"LUDU{sufijo}"
