from fastapi import APIRouter
from app.api.v1.endpoints import docentes, estudiantes, health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(estudiantes.router)
api_router.include_router(docentes.router)
