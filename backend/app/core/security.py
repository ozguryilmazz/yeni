from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def _create_token(subject: UUID, expires_delta: timedelta, token_type: Literal["access", "refresh"]) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: UUID) -> str:
    return _create_token(subject, timedelta(minutes=settings.access_token_expire_minutes), "access")


def create_refresh_token(subject: UUID) -> str:
    return _create_token(subject, timedelta(days=settings.refresh_token_expire_days), "refresh")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
