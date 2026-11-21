from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.db import get_session
from app.routers.auth import get_current_user
from app.models import User
from app.services.license.license import get_license_status


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/license")
async def license_status(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    status = await get_license_status(db)
    return status.model_dump()
