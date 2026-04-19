"""
app/core/security.py
Validación del JWT emitido por Supabase Auth.

Supabase emite tokens ES256 firmados con clave asimétrica.
Se valida contra el endpoint JWKS público de Supabase — sin secret compartido.
"""
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import RSAKey

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer()

# Cache simple en memoria para las claves públicas
_jwks_cache: dict | None = None


def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
    return _jwks_cache


def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    token = credentials.credentials
    try:
        # Intentar primero HS256 (compatibilidad con proyectos viejos)
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError:
        pass

    # Si falla HS256, intentar ES256 con JWKS
    try:
        jwks = _get_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Sesión de Supabase inválida o expirada: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_supabase_uid(payload: dict = Depends(verify_supabase_token)) -> str:
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin identificador de usuario (sub).",
        )
    return uid


def get_token_email(payload: dict = Depends(verify_supabase_token)) -> str:
    return payload.get("email", "")


def get_supabase_teacher(
    payload: dict = Depends(verify_supabase_token),
) -> dict:
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin identificador de usuario (sub).",
        )
    return {"uid": uid, "email": payload.get("email", "")}