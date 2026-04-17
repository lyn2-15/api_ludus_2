"""
app/api/v1/endpoints/docentes.py
Endpoints del docente — todos requieren JWT de Supabase.

CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR:
  - Se extrae `correo` del token en TODOS los endpoints y se pasa al
    servicio para que el auto-provisioning tenga el email real.
  - Nuevos endpoints para el flujo de onboarding del docente nuevo:
      GET  /docentes/perfil              → perfil + grupos (primer call al iniciar sesión)
      POST /docentes/grupos              → crear nuevo grupo
      GET  /docentes/grupos              → listar mis grupos

  - Endpoints existentes conservados sin cambios de contrato:
      POST /docentes/codigos
      GET  /docentes/analitica/grupo/{id_grupo}
      GET  /docentes/reportes/pdf/{uuid_estudiante}
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_supabase_uid, get_token_email, verify_supabase_token
from app.db.session import get_db
from app.schemas.schemas import (
    AnaliticaGrupoResponse,
    CrearGrupoRequest,
    GenerarCodigoRequest,
    GenerarCodigoResponse,
    GrupoResponse,
    ListaGruposResponse,
    MiPerfilResponse,
)
from app.services.docente_service import DocenteService

router = APIRouter(
    prefix="/docentes",
    tags=["📊 Docentes"],
    dependencies=[Depends(verify_supabase_token)],
)
service = DocenteService()


# ── Perfil y onboarding ───────────────────────────────────────────────────────

@router.get(
    "/perfil",
    response_model=MiPerfilResponse,
    summary="Mi perfil",
    description=(
        "Devuelve el perfil del docente autenticado y sus grupos. "
        "**Llamar siempre al iniciar sesión**: si el docente es nuevo, "
        "crea su perfil en SQLite automáticamente (auto-provisioning). "
        "Usar `tiene_grupos` para decidir si mostrar onboarding o dashboard."
    ),
)
async def mi_perfil(
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
) -> MiPerfilResponse:
    return await service.mi_perfil(db, supabase_uid, correo)


@router.get(
    "/grupos",
    response_model=ListaGruposResponse,
    summary="Mis grupos",
    description="Lista todos los grupos del docente autenticado con conteo de alumnos.",
)
async def listar_grupos(
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
) -> ListaGruposResponse:
    return await service.listar_mis_grupos(db, supabase_uid, correo)


@router.post(
    "/grupos",
    response_model=GrupoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear grupo",
    description=(
        "Crea un nuevo grupo escolar para el docente autenticado. "
        "**Este es el endpoint de onboarding**: un docente nuevo debe crear "
        "al menos un grupo antes de poder generar códigos o ver analíticas."
    ),
)
async def crear_grupo(
    payload: CrearGrupoRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
) -> GrupoResponse:
    return await service.crear_grupo(db, supabase_uid, correo, payload)


# ── Códigos de vinculación ────────────────────────────────────────────────────

@router.post(
    "/codigos",
    response_model=GenerarCodigoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar código de vinculación",
    description=(
        "Genera un código LUDUXX para que nuevos alumnos entren al grupo. "
        "**RLS**: solo puedes generar códigos para tus propios grupos."
    ),
)
async def generar_codigo(
    payload: GenerarCodigoRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
) -> GenerarCodigoResponse:
    return await service.generar_codigo(db, supabase_uid, correo, payload)


# ── Analítica ─────────────────────────────────────────────────────────────────

@router.get(
    "/analitica/grupo/{id_grupo}",
    response_model=AnaliticaGrupoResponse,
    summary="Analítica del grupo",
    description=(
        "Métricas pedagógicas de todos los alumnos del grupo. "
        "Usa `?metrica=errores` o `?metrica=progreso` para ordenar. "
        "**RLS**: solo puedes consultar tus grupos."
    ),
)
async def analitica_grupo(
    id_grupo: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
    metrica: Literal["errores", "progreso"] | None = Query(None),
) -> AnaliticaGrupoResponse:
    return await service.analitica_grupo(db, supabase_uid, correo, id_grupo, metrica)


# ── Reportes PDF ──────────────────────────────────────────────────────────────

@router.get(
    "/reportes/pdf/{uuid_estudiante}",
    summary="Reporte PDF del alumno",
    description=(
        "Genera PDF de progreso individual. "
        "Solo alias o UUID — nunca nombre real. "
        "**RLS**: el alumno debe pertenecer a uno de tus grupos."
    ),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def reporte_pdf(
    uuid_estudiante: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    supabase_uid: Annotated[str, Depends(get_supabase_uid)],
    correo: Annotated[str, Depends(get_token_email)],
):
    from fastapi import HTTPException
    from app.db.models import Estudiante, Grupo
    from app.services.reporte_service import ReporteService

    docente = await service.obtener_o_crear_docente(db, supabase_uid, correo)

    estudiante = await db.get(Estudiante, uuid_estudiante)
    if not estudiante:
        raise HTTPException(status_code=404, detail="Alumno no encontrado.")

    grupo = await db.get(Grupo, estudiante.id_grupo)
    if not grupo or grupo.id_docente != docente.id:
        raise HTTPException(
            status_code=403,
            detail="No tienes acceso a este alumno.",
        )

    pdf_bytes = await ReporteService().generar_pdf(db, estudiante, grupo.nombre_grupo)
    alias = estudiante.alias_estudiante or uuid_estudiante[:8]

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=reporte_{alias}.pdf"},
    )
