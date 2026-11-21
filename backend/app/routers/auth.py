from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.db import get_session
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    is_token_revoked,
    normalize_email,
    revoke_token,
    verify_password,
)
from app.core.config import settings
from app.models import User
from app.schemas.auth import PasswordChangeRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


async def get_auth_redis():
    redis = get_redis(settings.redis_url)
    try:
        yield redis
    finally:
        await redis.aclose()


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer),
    ],
    db=Depends(get_session),
    redis=Depends(get_auth_redis),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    jti = payload.get("jti")
    if not isinstance(jti, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    try:
        revoked = await is_token_revoked(redis, jti)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked")

    try:
        user_id = payload["sub"]
        workspace_id = payload["workspace_id"]
    except KeyError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token claims")

    try:
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.get(User, user_uuid)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if str(user.workspace_id) != workspace_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Workspace mismatch")
    return user


@router.post("/token", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db=Depends(get_session),
) -> TokenResponse:
    email = normalize_email(form.username)
    if "@" not in email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    result = await db.exec(select(User).where(User.email == email).limit(1))
    user = result.first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.totp_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "TOTP login is not enabled")

    return TokenResponse(access_token=create_access_token(user))


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(
        id=user.id,
        workspace_id=user.workspace_id,
        email=user.email,
        role=user.role,
    )


@router.post("/logout")
async def logout(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer),
    ],
    user: Annotated[User, Depends(get_current_user)],
    redis=Depends(get_auth_redis),
) -> dict[str, bool]:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = decode_access_token(credentials.credentials)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, (int, float)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    ttl = max(1, int(exp - datetime.now(timezone.utc).timestamp()))
    await revoke_token(redis, jti, ttl)
    return {"revoked": True}


@router.post("/password")
async def change_password(
    request: PasswordChangeRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict[str, bool]:
    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is invalid")
    if request.new_password == request.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password must change")

    user.password_hash = hash_password(request.new_password)
    db.add(user)
    await db.commit()
    return {"changed": True}
