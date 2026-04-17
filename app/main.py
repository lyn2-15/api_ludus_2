"""
app/main.py — LudusAcademia+ v2.1
Stack: FastAPI + SQLite3 (aiosqlite) + Supabase Auth
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="LudusAcademia+ API",
    description=(
        "Bridge offline-first entre la app Android y el Dashboard Docente. "
        "Stack: FastAPI · SQLite3 · Supabase Auth · v2.1"
    ),
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def limit_payload(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.MAX_SYNC_PAYLOAD_KB * 1024:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": f"Payload excede {settings.MAX_SYNC_PAYLOAD_KB}KB."},
        )
    return await call_next(request)


app.include_router(api_router)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Error interno. Reintenta en 15 minutos.",
            "retry_after_seconds": 900,
        },
    )
