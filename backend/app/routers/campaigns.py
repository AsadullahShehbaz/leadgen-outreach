from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.models import Campaign, Enrollment, SequenceStep, User, Workspace
from app.routers.auth import get_current_user
from app.schemas.dashboard import CampaignRequest, CampaignResponse, DraftResponse, SequenceStepRequest
from app.services.sequencing.state_machine import IllegalTransition, transition


router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _campaign(db, campaign_id: UUID, workspace_id: UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return campaign


async def _steps(db, campaign_id: UUID) -> list[SequenceStepRequest]:
    result = await db.exec(
        select(SequenceStep)
        .where(SequenceStep.campaign_id == campaign_id)
        .order_by(SequenceStep.step_no)
    )
    return [
        SequenceStepRequest(
            step_no=step.step_no,
            delay_days=step.delay_days,
            angle_hint=step.angle_hint,
        )
        for step in result.all()
    ]


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[CampaignResponse]:
    result = await db.exec(
        select(Campaign).where(Campaign.workspace_id == user.workspace_id)
    )
    return [
        CampaignResponse(
            id=campaign.id,
            name=campaign.name,
            product=campaign.product,
            icp=campaign.icp,
            status=campaign.status,
            compliance_mode=campaign.compliance_mode,
            require_approval=campaign.require_approval,
            sequence_steps=await _steps(db, campaign.id),
        )
        for campaign in result.all()
    ]


@router.post("", response_model=CampaignResponse)
async def create_campaign(
    request: CampaignRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> CampaignResponse:
    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None or not workspace.sender_identity or not workspace.postal_address or workspace.setup_responsibility_accepted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sender identity and responsibility acceptance are required")

    step_numbers = [step.step_no for step in request.sequence_steps]
    if len(step_numbers) != len(set(step_numbers)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sequence step numbers must be unique")

    campaign = Campaign(
        workspace_id=user.workspace_id,
        name=request.name.strip(),
        product=request.product,
        icp=request.icp,
        compliance_mode=request.compliance_mode,
        require_approval=request.require_approval,
        status="draft",
    )
    db.add(campaign)
    await db.flush()
    for step in request.sequence_steps:
        db.add(SequenceStep(
            campaign_id=campaign.id,
            step_no=step.step_no,
            delay_days=step.delay_days,
            angle_hint=step.angle_hint,
        ))
    await db.commit()
    await db.refresh(campaign)
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        product=campaign.product,
        icp=campaign.icp,
        status=campaign.status,
        compliance_mode=campaign.compliance_mode,
        require_approval=campaign.require_approval,
        sequence_steps=request.sequence_steps,
    )


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> CampaignResponse:
    campaign = await _campaign(db, campaign_id, user.workspace_id)
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        product=campaign.product,
        icp=campaign.icp,
        status=campaign.status,
        compliance_mode=campaign.compliance_mode,
        require_approval=campaign.require_approval,
        sequence_steps=await _steps(db, campaign.id),
    )


@router.get("/{campaign_id}/drafts", response_model=list[DraftResponse])
async def list_drafts(
    campaign_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> list[DraftResponse]:
    await _campaign(db, campaign_id, user.workspace_id)
    result = await db.exec(
        select(Enrollment).where(
            Enrollment.campaign_id == campaign_id,
            Enrollment.status == "drafted",
        )
    )
    drafts = []
    for enrollment in result.all():
        draft = enrollment.draft or {}
        drafts.append(DraftResponse(
            enrollment_id=enrollment.id,
            status=enrollment.status,
            subject=draft.get("subject"),
            body=draft.get("body"),
            claims=draft.get("claims", []) if isinstance(draft.get("claims", []), list) else [],
        ))
    return drafts


@router.post("/{campaign_id}/drafts/{enrollment_id}/approve", response_model=DraftResponse)
async def approve_draft(
    campaign_id: UUID,
    enrollment_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> DraftResponse:
    await _campaign(db, campaign_id, user.workspace_id)
    enrollment = await db.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    try:
        await transition(db, enrollment, "queued", "human_approved")
    except IllegalTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.add(enrollment)
    await db.commit()
    draft = enrollment.draft or {}
    return DraftResponse(
        enrollment_id=enrollment.id,
        status=enrollment.status,
        subject=draft.get("subject"),
        body=draft.get("body"),
        claims=draft.get("claims", []) if isinstance(draft.get("claims", []), list) else [],
    )


@router.post("/{campaign_id}/drafts/{enrollment_id}/reject", response_model=DraftResponse)
async def reject_draft(
    campaign_id: UUID,
    enrollment_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> DraftResponse:
    await _campaign(db, campaign_id, user.workspace_id)
    enrollment = await db.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    try:
        await transition(db, enrollment, "rejected", "human_rejected")
    except IllegalTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.commit()
    draft = enrollment.draft or {}
    return DraftResponse(
        enrollment_id=enrollment.id,
        status=enrollment.status,
        subject=draft.get("subject"),
        body=draft.get("body"),
        claims=draft.get("claims", []) if isinstance(draft.get("claims", []), list) else [],
    )
