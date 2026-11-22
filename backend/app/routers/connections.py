from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.db import get_session
from app.models import Connection, User
from app.routers.auth import get_current_user


router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
async def list_connections(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[dict]:
    result = await db.exec(
        select(Connection).where(Connection.workspace_id == user.workspace_id)
    )
    return [
        {"kind": connection.kind, "status": connection.status}
        for connection in result.all()
    ]
