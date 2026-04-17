"""
app/services/docente_service.py

CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR:
─────────────────────────────────────────────────────────────────────────────
PROBLEMA: Un docente nuevo registrado en Supabase no tenía registro en la
tabla `docentes` de SQLite, ni grupos asignados. Cualquier acción que
requiriera RLS fallaba con 403 aunque el JWT fuera válido.

SOLUCIÓN IMPLEMENTADA:
  1. `obtener_o_crear_docente()` ya hacía auto-provisioning, pero el correo
     llegaba vacío porque no se extraía del token. Ahora recibe `correo`
     como parámetro obligatorio (viene del JWT de Supabase).

  2. Se agregan tres métodos nuevos:
     - `crear_grupo()`: permite al docente crear su PRIMER grupo (o más).
       Sin este endpoint, un docente nuevo no tenía forma de tener grupos
       y todas las acciones con RLS fallaban.
     - `listar_mis_grupos()`: devuelve los grupos del docente con conteo
       de alumnos. El dashboard lo usa para poblar el selector de grupo.
     - `mi_perfil()`: devuelve perfil + grupos. El frontend lo llama al
       iniciar sesión para saber si mostrar onboarding ("Crea tu primer
       grupo") o ir directo al dashboard.

  3. `generar_codigo()` y `analitica_grupo()` ahora llaman a
     `obtener_o_crear_docente()` con el correo del token, garantizando
     que el perfil siempre exista antes de la validación RLS.
─────────────────────────────────────────────────────────────────────────────
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CodigoVinculacion, Docente, Estudiante, EventoAprendizaje, Grupo
from app.schemas.schemas import (
    AnaliticaGrupoResponse,
    CrearGrupoRequest,
    GenerarCodigoRequest,
    GenerarCodigoResponse,
    GrupoResponse,
    ListaGruposResponse,
    MetricaAlumno,
    MiPerfilResponse,
)
from app.services.estudiante_service import generar_codigo_ludu

settings = get_settings()


class DocenteService:

    # ── Auto-provisioning ─────────────────────────────────────────────────────

    async def obtener_o_crear_docente(
        self,
        db: AsyncSession,
        supabase_uid: str,
        correo: str = "",
    ) -> Docente:
        """
        Obtiene el registro del docente por supabase_uid.
        Si no existe (docente nuevo de Supabase), lo crea automáticamente.

        Este método es la piedra angular del fix: garantiza que cualquier
        docente con JWT válido tenga siempre un registro en SQLite antes
        de que el código RLS intente leerlo.

        El `correo` viene del payload del JWT (campo 'email') y se usa
        al crear el perfil por primera vez.
        """
        result = await db.execute(
            select(Docente).where(Docente.supabase_uid == supabase_uid)
        )
        docente = result.scalar_one_or_none()

        if not docente:
            docente = Docente(
                supabase_uid=supabase_uid,
                correo=correo or f"{supabase_uid[:8]}@supabase.local",
            )
            db.add(docente)
            await db.flush()  # Necesario para obtener docente.id antes del commit

        return docente

    # ── Perfil y grupos ───────────────────────────────────────────────────────

    async def mi_perfil(
        self, db: AsyncSession, supabase_uid: str, correo: str
    ) -> MiPerfilResponse:
        """
        Devuelve el perfil del docente + lista de sus grupos.

        El dashboard llama a este endpoint al iniciar sesión para:
          - Verificar que el perfil existe en SQLite (se crea si no)
          - Saber si mostrar onboarding ("Crea tu primer grupo")
            o ir directo al listado de grupos
        """
        docente = await self.obtener_o_crear_docente(db, supabase_uid, correo)
        grupos = await self._grupos_con_conteo(db, docente.id)

        return MiPerfilResponse(
            id=docente.id,
            correo=docente.correo,
            nombre_completo=docente.nombre_completo,
            fecha_registro=docente.fecha_registro,
            grupos=grupos,
            tiene_grupos=len(grupos) > 0,
        )

    async def listar_mis_grupos(
        self, db: AsyncSession, supabase_uid: str, correo: str
    ) -> ListaGruposResponse:
        """Devuelve todos los grupos del docente con conteo de alumnos."""
        docente = await self.obtener_o_crear_docente(db, supabase_uid, correo)
        grupos = await self._grupos_con_conteo(db, docente.id)
        return ListaGruposResponse(grupos=grupos, total=len(grupos))

    async def crear_grupo(
        self,
        db: AsyncSession,
        supabase_uid: str,
        correo: str,
        payload: CrearGrupoRequest,
    ) -> GrupoResponse:
        """
        Crea un nuevo grupo para el docente autenticado.

        Este endpoint resuelve el problema raíz: un docente nuevo con JWT
        válido pero sin grupos en SQLite no podía hacer NADA porque todas
        las acciones con RLS requerían tener al menos un grupo.

        Ahora el flujo de onboarding es:
          1. Docente se registra en Supabase (web)
          2. Llama a GET /docentes/perfil → se crea su perfil, tiene_grupos=false
          3. Dashboard muestra pantalla "Crea tu primer grupo"
          4. Docente llena el formulario → POST /docentes/grupos
          5. Ahora puede generar códigos y ver analíticas
        """
        docente = await self.obtener_o_crear_docente(db, supabase_uid, correo)

        nuevo_grupo = Grupo(
            id_docente=docente.id,
            nombre_grupo=payload.nombre_grupo,
            nombre_escuela=payload.nombre_escuela,
        )
        db.add(nuevo_grupo)
        await db.flush()

        return GrupoResponse(
            id=nuevo_grupo.id,
            nombre_grupo=nuevo_grupo.nombre_grupo,
            nombre_escuela=nuevo_grupo.nombre_escuela,
            total_estudiantes=0,
        )

    # ── Códigos de vinculación ────────────────────────────────────────────────

    async def generar_codigo(
        self,
        db: AsyncSession,
        supabase_uid: str,
        correo: str,
        payload: GenerarCodigoRequest,
    ) -> GenerarCodigoResponse:
        """
        Genera un código LUDUXX para que alumnos entren al grupo.
        RLS: el grupo debe pertenecer al docente autenticado.
        """
        docente = await self.obtener_o_crear_docente(db, supabase_uid, correo)

        grupo = await db.get(Grupo, payload.id_grupo)
        if not grupo or grupo.id_docente != docente.id:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para generar códigos en este grupo.",
            )

        expira = datetime.now(timezone.utc) + timedelta(hours=payload.horas_validez)

        # Reintentar hasta encontrar un código libre (colisión muy improbable)
        for _ in range(10):
            codigo_str = generar_codigo_ludu()
            if not await db.get(CodigoVinculacion, codigo_str):
                break

        db.add(CodigoVinculacion(
            codigo=codigo_str,
            id_grupo=payload.id_grupo,
            expira_el=expira,
            esta_usado=False,
        ))

        return GenerarCodigoResponse(
            codigo_vinculacion=codigo_str,
            expira_el=expira,
        )

    # ── Analítica ─────────────────────────────────────────────────────────────

    async def analitica_grupo(
        self,
        db: AsyncSession,
        supabase_uid: str,
        correo: str,
        id_grupo: int,
        metrica: str | None,
    ) -> AnaliticaGrupoResponse:
        """
        Métricas pedagógicas del grupo para el dashboard.
        RLS: el docente solo puede consultar sus propios grupos.
        Los alumnos aparecen con alias — nunca con nombre real.
        """
        docente = await self.obtener_o_crear_docente(db, supabase_uid, correo)

        grupo = await db.get(Grupo, id_grupo)
        if not grupo or grupo.id_docente != docente.id:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para consultar este grupo.",
            )

        result = await db.execute(
            select(Estudiante).where(Estudiante.id_grupo == id_grupo)
        )
        alumnos = result.scalars().all()

        metricas = []
        for alumno in alumnos:
            stats = await db.execute(
                select(
                    func.count(EventoAprendizaje.id_evento).label("total_misiones"),
                    func.coalesce(func.avg(EventoAprendizaje.errores), 0.0).label("prom_errores"),
                    func.max(EventoAprendizaje.fecha_servidor).label("ultima_actividad"),
                ).where(EventoAprendizaje.uuid_estudiante == alumno.uuid_estudiante)
            )
            row = stats.one()

            metricas.append(MetricaAlumno(
                alias_alumno=alumno.alias_estudiante or alumno.uuid_estudiante[:8],
                misiones_completas=row.total_misiones or 0,
                promedio_errores=round(float(row.prom_errores), 2),
                monedas_totales=alumno.monedas_totales,
                ultima_actividad=row.ultima_actividad,
            ))

        if metrica == "errores":
            metricas.sort(key=lambda m: m.promedio_errores, reverse=True)
        elif metrica == "progreso":
            metricas.sort(key=lambda m: m.misiones_completas, reverse=True)

        return AnaliticaGrupoResponse(
            id_grupo=id_grupo,
            nombre_grupo=grupo.nombre_grupo,
            total_alumnos=len(metricas),
            metricas=metricas,
            generado_el=datetime.now(timezone.utc),
        )

    # ── Helper privado ────────────────────────────────────────────────────────

    async def _grupos_con_conteo(
        self, db: AsyncSession, id_docente: int
    ) -> list[GrupoResponse]:
        """Devuelve los grupos del docente con conteo de alumnos cada uno."""
        result = await db.execute(
            select(Grupo).where(Grupo.id_docente == id_docente)
        )
        grupos = result.scalars().all()

        respuesta = []
        for grupo in grupos:
            total = await db.scalar(
                select(func.count(Estudiante.uuid_estudiante))
                .where(Estudiante.id_grupo == grupo.id)
            ) or 0
            respuesta.append(GrupoResponse(
                id=grupo.id,
                nombre_grupo=grupo.nombre_grupo,
                nombre_escuela=grupo.nombre_escuela,
                total_estudiantes=total,
            ))

        return respuesta
