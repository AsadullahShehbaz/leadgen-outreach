import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

from app.core.config import settings
from app.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("Password is required")

    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        password_bytes = b"sha256:" + hashlib.sha256(password_bytes).digest()
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    if not password or not password_hash:
        return False

    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        password_bytes = b"sha256:" + hashlib.sha256(password_bytes).digest()
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def create_access_token(
    user: User,
    expires_minutes: int | None = None,
) -> str:
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "jti": secrets.token_urlsafe(32),
        "workspace_id": str(user.workspace_id),
        "role": user.role,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
    )


async def is_token_revoked(redis: Any, jti: str) -> bool:
    try:
        value = await redis.get(f"jwt:blacklist:{jti}")
        return value is not None
    except Exception:
        # Revocation must fail closed when Redis is unavailable.
        raise RuntimeError("Token revocation store is unavailable")


async def revoke_token(redis: Any, jti: str, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    await redis.set(
        f"jwt:blacklist:{jti}",
        "revoked",
        ex=ttl_seconds,
    )


def _fernet(fernet_key: str | None = None) -> Fernet:
    key = fernet_key or settings.FERNET_KEY
    if not key:
        raise ValueError("FERNET_KEY is required")
    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("FERNET_KEY must be a valid Fernet key") from exc


def encrypt_secret(secret: dict[str, Any], fernet_key: str | None = None) -> str:
    payload = json.dumps(secret, separators=(",", ":"), sort_keys=True)
    return _fernet(fernet_key).encrypt(payload.encode("utf-8")).decode("ascii")


def decrypt_secret(encrypted: str, fernet_key: str | None = None) -> dict[str, Any]:
    try:
        payload = _fernet(fernet_key).decrypt(encrypted.encode("ascii"))
        value = json.loads(payload.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError, InvalidToken) as exc:
        raise ValueError("Stored secret is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("Stored secret must be a JSON object")
    return value
