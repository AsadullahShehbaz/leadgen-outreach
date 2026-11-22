from typing import Annotated
from uuid import UUID
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.models import Lead, LeadEmail, User
from app.routers.auth import get_current_user
from app.schemas.dashboard import CsvImportRequest, LeadResponse
from app.services.sources.csv_import import parse_csv
from app.services.sources.pipeline import persist_raw_leads
from app.services.compliance.suppression import add_suppression
from app.services.compliance.forget_person import forget_person
from app.routers.compliance import SqlSuppressionStore


router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=list[LeadResponse])
async def list_leads(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[LeadResponse]:
    result = await db.exec(select(Lead).where(Lead.workspace_id == user.workspace_id))
    response = []
    for lead in result.all():
        email_result = await db.exec(
            select(LeadEmail).where(LeadEmail.lead_id == lead.id).limit(1)
        )
        lead_email = email_result.first()
        response.append(LeadResponse(
            id=lead.id,
            company_name=lead.company_name,
            company_domain=lead.company_domain,
            person_name=lead.person_name,
            title=lead.title,
            country=lead.country,
            icp_score=lead.icp_score,
            lawful_basis=lead.lawful_basis,
            verify_status=lead_email.verify_status if lead_email else "unknown",
        ))
    return response


@router.post("/import/csv")
async def import_csv(
    request: CsvImportRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    try:
        reader = csv.DictReader(io.StringIO(request.csv_text))
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    try:
        raw_leads = parse_csv(request.csv_text)
        imported = await persist_raw_leads(db, user.workspace_id, raw_leads)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return {"imported": imported, "rows": len(rows)}


@router.post("/{lead_id}/forget")
async def forget_lead(
    lead_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    lead = await db.get(Lead, lead_id)
    if lead is None or lead.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    email_result = await db.exec(
        select(LeadEmail).where(LeadEmail.lead_id == lead.id).limit(1)
    )
    lead_email = email_result.first()
    if lead_email is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead email not found")

    class LeadForgetStore:
        async def forget_lead(self, lead_id: str, email: str) -> None:
            target = await db.get(Lead, UUID(lead_id))
            if target is not None:
                target.person_name = None
                target.title = None
                target.raw = {}
                db.add(target)
                emails = (await db.exec(
                    select(LeadEmail).where(LeadEmail.lead_id == target.id)
                )).all()
                for item in emails:
                    await db.delete(item)

    await forget_person(
        LeadForgetStore(),
        SqlSuppressionStore(db),
        str(lead.id),
        lead_email.email,
    )
    await db.commit()
    return {"forgotten": True}
