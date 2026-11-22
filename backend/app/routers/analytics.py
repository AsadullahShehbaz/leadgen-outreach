from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.db import get_session
from app.models import (
    Campaign,
    Enrollment,
    Event,
    Experiment,
    Lead,
    LeadEmail,
    Mailbox,
    SpendLedger,
    User,
    Workspace,
)
from app.routers.auth import get_current_user
from app.services.agents.optimizer import build_weekly_report, rank_leads


router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _campaign_ids(db, workspace_id) -> list:
    result = await db.exec(
        select(Campaign.id).where(Campaign.workspace_id == workspace_id)
    )
    return list(result.all())


@router.get("/summary")
async def analytics_summary(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    campaign_ids = (
        await db.exec(
            select(Campaign.id).where(Campaign.workspace_id == user.workspace_id)
        )
    ).all()

    lead_count = (
        await db.exec(
            select(func.count()).select_from(Lead).where(Lead.workspace_id == user.workspace_id)
        )
    ).one()

    enrollment_counts = {}
    for status in ("drafted", "queued", "step1_sent", "step2_sent", "step3_sent", "completed", "replied", "bounced", "unsubscribed"):
        count = (
            await db.exec(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.campaign_id.in_(campaign_ids),
                    Enrollment.status == status,
                )
            )
        ).one()
        enrollment_counts[status] = count

    today = date.today()
    today_spend = (
        await db.exec(
            select(func.coalesce(func.sum(SpendLedger.est_usd), 0.0)).where(
                SpendLedger.day == today
            )
        )
    ).one()

    mailbox_count = (
        await db.exec(
            select(func.count()).select_from(Mailbox).where(Mailbox.workspace_id == user.workspace_id)
        )
    ).one()

    return {
        "leads": lead_count,
        "enrollments": enrollment_counts,
        "spend_today_usd": float(today_spend),
        "mailboxes": mailbox_count,
        "open_tracking_pixels": 0,
    }


@router.get("/optimizer")
async def optimizer_status(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    campaign_ids = await _campaign_ids(db, user.workspace_id)
    experiments = []
    if campaign_ids:
        result = await db.exec(
            select(Experiment).where(Experiment.campaign_id.in_(campaign_ids))
        )
        for experiment in result.all():
            experiments.append({
                "campaign_id": str(experiment.campaign_id),
                "kind": experiment.kind,
                "variants": experiment.stats,
            })

    pending_result = await db.exec(
        select(Enrollment, Lead)
        .join(Lead, Enrollment.lead_id == Lead.id)
        .where(
            Enrollment.campaign_id.in_(campaign_ids) if campaign_ids else Enrollment.id.is_(None),
            Enrollment.status.in_(("new", "verified", "drafted", "queued")),
        )
        .limit(500)
    )
    lead_rows = [
        {
            "id": str(enrollment.id),
            "icp_score": lead.icp_score,
            "industry": lead.company_name,
            "size": lead.raw.get("size") if isinstance(lead.raw, dict) else None,
            "title": lead.title,
            "country": lead.country,
        }
        for enrollment, lead in pending_result.all()
    ]
    ranked = rank_leads(lead_rows)
    return {
        "experiments": experiments,
        "pending_leads_ranked": ranked,
        "minimum_sample_default": 30,
        "open_tracking_pixels": 0,
    }


@router.get("/report/preview")
async def weekly_report_preview(
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict:
    workspace = await db.get(Workspace, user.workspace_id)
    campaign_ids = await _campaign_ids(db, user.workspace_id)
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    sent = 0
    positive_replies = 0
    best_angle = None
    if campaign_ids:
        from app.models import Message

        sent_messages = (
            await db.exec(
                select(Message).join(
                    Enrollment,
                    Message.enrollment_id == Enrollment.id,
                ).where(
                    Enrollment.campaign_id.in_(campaign_ids),
                    Message.direction == "out",
                    Message.sent_at >= week_start,
                    Message.sent_at <= now,
                )
            )
        ).all()
        sent = len(sent_messages)

        events = (
            await db.exec(
                select(Event).join(
                    Enrollment,
                    Event.enrollment_id == Enrollment.id,
                ).join(
                    Campaign,
                    Enrollment.campaign_id == Campaign.id,
                ).where(
                    Campaign.workspace_id == user.workspace_id,
                    Event.type == "state",
                    Event.at >= week_start,
                    Event.at <= now,
                )
            )
        ).all()
        positive_replies = sum(
            1
            for event in events
            if isinstance(event.payload, dict)
            and event.payload.get("reply_class") in {"interested", "question"}
        )

    report = build_weekly_report(
        workspace_name=workspace.name if workspace is not None else "Workspace",
        week_start=week_start,
        sent=sent,
        positive_replies=positive_replies,
        best_segment=None,
        best_angle=best_angle,
        spend_by_kind={"llm": 0.0, "verify": 0.0, "source": 0.0},
    )
    return report
