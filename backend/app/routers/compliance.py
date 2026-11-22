from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.models import Lead, LeadEmail, Suppression, User, Workspace
from app.models.base import utcnow
from app.routers.auth import get_current_user
from app.schemas.dashboard import ComplianceSettingsRequest, SuppressionRequest, SuppressionResponse
from app.services.compliance.suppression import add_suppression, domain_from_email, hash_email


router = APIRouter(prefix="/compliance", tags=["compliance"])


class SqlSuppressionStore:
    def __init__(self, db):
        self.db = db

    async def add(self, email_hash: str, domain: str | None, reason: str) -> None:
        result = await self.db.exec(
            select(Suppression).where(Suppression.email_hash == email_hash).limit(1)
        )
        existing = result.first()
        if existing is None:
            self.db.add(Suppression(
                email_hash=email_hash,
                domain=domain,
                reason=reason,
            ))
        else:
            existing.reason = reason
            existing.domain = domain
            existing.at = utcnow()
            self.db.add(existing)

    async def find_email(self, email_hash: str) -> bool:
        result = await self.db.exec(
            select(Suppression).where(Suppression.email_hash == email_hash).limit(1)
        )
        return result.first() is not None

    async def find_domain(self, domain: str) -> bool:
        result = await self.db.exec(
            select(Suppression).where(Suppression.domain == domain).limit(1)
        )
        return result.first() is not None


@router.get("/suppression", response_model=list[SuppressionResponse])
async def list_suppression(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[SuppressionResponse]:
    result = await db.exec(select(Suppression).order_by(Suppression.at.desc()).limit(500))
    return [
        SuppressionResponse(
            email_hash=item.email_hash,
            domain=item.domain,
            reason=item.reason,
            at=item.at,
        )
        for item in result.all()
    ]


@router.post("/suppression", response_model=SuppressionResponse)
async def add_suppression_endpoint(
    request: SuppressionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> SuppressionResponse:
    store = SqlSuppressionStore(db)
    try:
        email_hash = await add_suppression(store, request.email, request.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    await db.commit()
    result = await db.exec(
        select(Suppression).where(Suppression.email_hash == email_hash).limit(1)
    )
    item = result.first()
    return SuppressionResponse(
        email_hash=item.email_hash,
        domain=item.domain,
        reason=item.reason,
        at=item.at,
    )


@router.delete("/suppression/{email_hash}")
async def remove_suppression(
    email_hash: str,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    result = await db.exec(
        select(Suppression).where(Suppression.email_hash == email_hash).limit(1)
    )
    item = result.first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suppression not found")
    await db.delete(item)
    await db.commit()
    return {"removed": True}


@router.put("/settings")
async def update_compliance_settings(
    request: ComplianceSettingsRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    workspace.sender_identity = request.sender_identity
    workspace.postal_address = request.postal_address
    workspace.footer_text = request.footer_text
    workspace.timezone = request.timezone
    db.add(workspace)
    await db.commit()
    return {"updated": True}
