from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.models import Campaign, Enrollment, Message, User
from app.routers.auth import get_current_user
from app.schemas.dashboard import InboxResponse


router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=list[InboxResponse])
async def list_inbox(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
    limit: int = 100,
) -> list[InboxResponse]:
    limit = min(max(limit, 1), 500)
    result = await db.exec(
        select(Message, Enrollment)
        .join(Enrollment, Enrollment.id == Message.enrollment_id)
        .join(Campaign, Campaign.id == Enrollment.campaign_id)
        .where(Campaign.workspace_id == user.workspace_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return [
        InboxResponse(
            id=message.id,
            direction=message.direction,
            message_id=message.message_id,
            subject=message.subject,
            body=message.body,
            sent_at=message.sent_at,
            enrollment_id=message.enrollment_id,
        )
        for message, _enrollment in result.all()
    ]
