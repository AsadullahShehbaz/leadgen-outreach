from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.db import get_session
from app.models import Domain, User
from app.routers.auth import get_current_user


router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("")
async def list_domains(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[dict]:
    result = await db.exec(
        select(Domain).where(Domain.workspace_id == user.workspace_id)
    )
    return [
        {
            "id": domain.id,
            "name": domain.name,
            "spf_ok": domain.spf_ok,
            "dkim_ok": domain.dkim_ok,
            "dmarc_ok": domain.dmarc_ok,
        }
        for domain in result.all()
    ]
