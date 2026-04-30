"""
Finoks — JWT creation/verification and password hashing.

Uses ``passlib[bcrypt]`` for hashing and ``python-jose`` for JWT signing (HS256).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALG = "HS256"
DEFAULT_EXPIRES_MINUTES = 60 * 24


def _secret() -> str:
    return os.getenv("JWT_SECRET", "finoks-dev-secret-change-me")


def hash_password(plain: str) -> str:
    """Hash a password for storage."""

    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext against stored hash."""

    if not plain or not hashed:
        return False
    try:
        return _pwd_ctx.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """Create a signed JWT for the given subject (e.g. email or user id)."""

    expires = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else DEFAULT_EXPIRES_MINUTES
    )
    payload = {"sub": str(subject), "exp": int(expires.timestamp())}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate JWT; return claims or ``None`` if invalid."""

    if not token:
        return None
    try:
        return jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    except JWTError:
        return None
