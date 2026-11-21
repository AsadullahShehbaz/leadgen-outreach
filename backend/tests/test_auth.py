from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    is_token_revoked,
    revoke_token,
    verify_password,
)
from app.models import User


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int):
        self.values[key] = value
        return True


def test_password_hash_verifies():
    password_hash = hash_password("correct horse battery")
    assert password_hash != "correct horse battery"
    assert verify_password("correct horse battery", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_password_hash_handles_long_password():
    password = "x" * 100
    password_hash = hash_password(password)
    assert verify_password(password, password_hash)
    assert not verify_password("x" * 99, password_hash)


def test_access_token_has_workspace_claims():
    user = User(
        workspace_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        password_hash=hash_password("password-12345"),
        role="admin",
    )
    token = create_access_token(user)
    payload = decode_access_token(token)
    assert payload["sub"] == str(user.id)
    assert payload["workspace_id"] == str(user.workspace_id)
    assert payload["role"] == "admin"
    assert payload["jti"]


def test_expired_access_token_is_rejected():
    expired = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "jti": "expired",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


async def test_revoked_token_is_detected():
    redis = FakeRedis()
    await revoke_token(redis, "token-jti", 60)
    assert await is_token_revoked(redis, "token-jti")
    assert not await is_token_revoked(redis, "other-jti")


def test_fernet_secret_round_trip():
    key = Fernet.generate_key().decode()
    encrypted = encrypt_secret({"api_key": "fake-key", "host": "example.test"}, key)
    assert "fake-key" not in encrypted
    assert decrypt_secret(encrypted, key) == {"api_key": "fake-key", "host": "example.test"}


def test_invalid_fernet_key_is_rejected():
    with pytest.raises(ValueError):
        encrypt_secret({"api_key": "fake-key"}, "not-a-fernet-key")
