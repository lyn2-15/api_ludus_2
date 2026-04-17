"""
app/api/v1/endpoints/health.py
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.schemas import HealthResponse

router = APIRouter(tags=["🩺 Health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse, summary="Estado del servidor")
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return HealthResponse(
        estado="ok" if db_ok else "degradado",
        version="2.1.0",
        entorno=settings.APP_ENV,
    )
