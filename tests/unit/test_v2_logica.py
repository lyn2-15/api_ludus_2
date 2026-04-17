"""
tests/unit/test_v2_logica.py
Tests unitarios para la lógica crítica de v2.1
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.schemas import (
    CrearGrupoRequest,
    EventoAprendizajeIn,
    SincronizarRequest,
    VincularRequest,
)
from app.services.estudiante_service import EstudianteService, generar_codigo_ludu
from app.services.docente_service import DocenteService


# ── Generador de códigos ──────────────────────────────────────────────────────

def test_codigo_ludu_formato():
    for _ in range(50):
        codigo = generar_codigo_ludu()
        assert len(codigo) == 6
        assert codigo.startswith("LUDU")
        sufijo = codigo[4:]
        assert "O" not in sufijo and "0" not in sufijo
        assert "I" not in sufijo and "1" not in sufijo


def test_codigos_son_variados():
    codigos = {generar_codigo_ludu() for _ in range(30)}
    assert len(codigos) > 15


# ── Auto-provisioning (el fix central) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_obtener_o_crear_docente_nuevo():
    """
    CASO CRÍTICO: Docente registrado en Supabase pero sin perfil en SQLite.
    obtener_o_crear_docente() debe crear el perfil automáticamente.
    """
    service = DocenteService()

    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None  # No existe

    docente_mock = MagicMock()
    docente_mock.id = 99

    db.flush = AsyncMock()

    with patch("app.services.docente_service.Docente") as MockDocente:
        MockDocente.return_value = docente_mock
        result = await service.obtener_o_crear_docente(
            db, "supabase-uid-nuevo", "nuevo@escuela.mx"
        )

    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_obtener_o_crear_docente_existente_no_duplica():
    """Un docente que ya existe no debe crear un registro duplicado."""
    service = DocenteService()

    docente_existente = MagicMock()
    docente_existente.id = 5

    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = docente_existente

    result = await service.obtener_o_crear_docente(db, "uid-existente", "")

    db.add.assert_not_called()
    assert result.id == 5


# ── Crear grupo (onboarding) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_grupo_primer_grupo_docente_nuevo():
    """
    Un docente nuevo debe poder crear su primer grupo sin errores.
    Este es el flujo que fallaba antes del fix.
    """
    service = DocenteService()

    docente_mock = MagicMock()
    docente_mock.id = 1

    grupo_mock = MagicMock()
    grupo_mock.id = 10
    grupo_mock.nombre_grupo = "3° A Prueba"
    grupo_mock.nombre_escuela = "Escuela 5 de Mayo de 1862"

    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None  # Docente nuevo

    with patch.object(service, "obtener_o_crear_docente", return_value=docente_mock):
        from app.db.models import Grupo as GrupoModel
        with patch("app.services.docente_service.Grupo") as MockGrupo:
            MockGrupo.return_value = grupo_mock
            payload = CrearGrupoRequest(nombre_grupo="3° A Prueba")
            result = await service.crear_grupo(db, "uid-nuevo", "doc@test.mx", payload)

    db.add.assert_called_once()
    db.flush.assert_called_once()


# ── Vinculación ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vincular_codigo_expirado_lanza_404():
    service = EstudianteService()
    payload = VincularRequest(uuid_estudiante="uuid-001", codigo_vinculacion="LUDU42")

    codigo_mock = MagicMock()
    codigo_mock.esta_usado = False
    codigo_mock.expira_el = datetime.now(timezone.utc) - timedelta(hours=1)

    db = AsyncMock()
    db.get.return_value = codigo_mock

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await service.vincular(db, payload)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_vincular_codigo_ya_usado_lanza_404():
    service = EstudianteService()
    payload = VincularRequest(uuid_estudiante="uuid-002", codigo_vinculacion="LUDU99")

    codigo_mock = MagicMock()
    codigo_mock.esta_usado = True
    codigo_mock.expira_el = datetime.now(timezone.utc) + timedelta(hours=23)

    db = AsyncMock()
    db.get.return_value = codigo_mock

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await service.vincular(db, payload)
    assert exc.value.status_code == 404


# ── Sincronización ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_alumno_no_vinculado_lanza_403():
    service = EstudianteService()
    payload = SincronizarRequest(
        uuid_estudiante="uuid-desconocido",
        eventos=[EventoAprendizajeIn(
            id_evento="evt-001", id_mision="frac_01",
            errores=2, segundos_jugados=90, monedas_ganadas=50,
            fecha_dispositivo=datetime.now(timezone.utc),
        )],
    )
    db = AsyncMock()
    db.get.return_value = None

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await service.sincronizar(db, payload)
    assert exc.value.status_code == 403


# ── Validaciones de schema ────────────────────────────────────────────────────

def test_schema_codigo_normaliza_minusculas():
    req = VincularRequest(uuid_estudiante="uuid-xyz", codigo_vinculacion="ludu42")
    assert req.codigo_vinculacion == "LUDU42"


def test_schema_evento_rechaza_tiempo_negativo():
    with pytest.raises(Exception):
        EventoAprendizajeIn(
            id_evento="evt-x", id_mision="geo_01",
            errores=0, segundos_jugados=-5,
            monedas_ganadas=0,
            fecha_dispositivo=datetime.now(timezone.utc),
        )


def test_schema_crear_grupo_requiere_nombre():
    with pytest.raises(Exception):
        CrearGrupoRequest(nombre_grupo="")
