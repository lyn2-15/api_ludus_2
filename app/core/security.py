"""
app/core/security.py
Validación del JWT emitido por Supabase Auth.

FastAPI actúa como "Resource Server" — valida la firma del JWT de Supabase
usando SUPABASE_JWT_SECRET (HMAC-SHA256) sin llamadas HTTP externas.

El payload del JWT de Supabase incluye:
  - sub:   UUID del usuario en Supabase (supabase_uid)
  - email: correo del docente
  - exp:   expiración
"""
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer()


def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    """
    Extrae y valida el Bearer JWT de Supabase.
    Devuelve el payload completo — 'sub' es el supabase_uid del docente.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
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
    """Extrae el supabase_uid (campo 'sub') del token validado."""
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin identificador de usuario (sub).",
        )
    return uid


def get_token_email(payload: dict = Depends(verify_supabase_token)) -> str:
    """Extrae el email del payload del token. Puede estar vacío."""
    return payload.get("email", "")
