from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.models import Mailbox, User
from app.routers.auth import get_current_user


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


@router.get("")
async def list_mailboxes(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[dict]:
    result = await db.exec(
        select(Mailbox).where(Mailbox.workspace_id == user.workspace_id)
    )
    return [
        {
            "id": mailbox.id,
            "address": mailbox.address,
            "domain_id": mailbox.domain_id,
            "daily_cap": mailbox.daily_cap,
            "status": mailbox.status,
            "health_score": mailbox.health_score,
        }
        for mailbox in result.all()
    ]


@router.patch("/{mailbox_id}")
async def update_mailbox(
    mailbox_id: UUID,
    payload: dict,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    mailbox = await db.get(Mailbox, mailbox_id)
    if mailbox is None or mailbox.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mailbox not found")

    if "status" not in payload or payload["status"] not in {"active", "paused", "warming"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid mailbox status")
    mailbox.status = payload["status"]
    db.add(mailbox)
    await db.commit()
    return {"id": mailbox.id, "status": mailbox.status}
