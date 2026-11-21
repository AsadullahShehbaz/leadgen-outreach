from app.core.config import settings
from app.core.db import Session
from app.core.redis import get_redis
from app.services.agents.reply_classifier import FakeReplyClassifier
from app.services.budget.spend_caps import SqlSpendLedgerStore
from app.services.sequencing.inbox_worker import poll_inbox as poll_inbox_engine
from app.services.sequencing.send_due import send_due as send_due_engine
from app.services.sources.pipeline import source_leads as source_leads_engine
from app.services.verify.mx import DnsMxLookup
from app.services.verify.pipeline import verify_lead_emails as verify_lead_emails_engine
from app.models import Campaign, Enrollment, Lead, LeadEmail
from app.services.agents.personalize_graph import personalize_enrollment
from app.services.agents.research import FakeResearchClient
from app.services.agents.llm import GroqLLMClient
from app.models.base import utcnow
from app.services.license.license import (
    InvalidLicense,
    license_allows_sourcing,
    refresh_license_state,
)


async def license_check(ctx: dict) -> dict:
    """Validate the stored license offline once per day."""
    session = ctx.get("session")
    if session is not None:
        return await _license_check_session(session)

    async with Session() as db:
        return await _license_check_session(db)


async def _license_check_session(db) -> dict:
    from sqlalchemy import select
    from app.models import LicenseState

    result = await db.exec(
        select(LicenseState).order_by(LicenseState.created_at.desc()).limit(1)
    )
    state = result.first()
    if state is None:
        return {"valid": False, "reason": "License is missing"}
    key = settings.LICENSE_PUBLIC_KEY_PEM
    if not key:
        return {"valid": False, "reason": "License public key is missing"}
    try:
        status = await refresh_license_state(db, state.token, key)
    except InvalidLicense:
        state.valid_until = None
        state.last_checked_at = utcnow()
        db.add(state)
        await db.commit()
        return {"valid": False, "reason": "License is invalid"}
    return {
        "valid": status.valid,
        "in_grace": status.in_grace,
        "expires_at": status.expires_at.isoformat() if status.expires_at else None,
        "reason": status.reason,
    }


async def send_due(ctx: dict) -> int:
    redis = ctx.get("redis")
    if redis is None:
        redis = get_redis(settings.redis_url)

    try:
        return await send_due_engine(
            {
                "redis": redis,
                "mail": ctx["mail"],
                "session": Session,
                "now": ctx.get("now"),
                "public_url": ctx.get("public_url", settings.PUBLIC_URL),
                "sending_enabled": ctx.get("sending_enabled", settings.SENDING_ENABLED),
            }
        )
    finally:
        if ctx.get("redis") is None:
            await redis.aclose()


async def poll_inbox(ctx: dict) -> int:
    """Poll every active mailbox for bounces and replies."""
    return await poll_inbox_engine(
        {
            "mail": ctx["mail"],
            "session": ctx.get("session", Session),
            "reply_classifier": ctx.get("reply_classifier", FakeReplyClassifier()),
            "mailbox_uids": ctx.setdefault("mailbox_uids", {}),
        }
    )


async def source_leads(ctx: dict) -> dict:
    session = ctx["session"]
    source = ctx["source"]
    return await source_leads_engine(
        session=session,
        source=source,
        query=ctx.get("query", {}),
        workspace_id=ctx["workspace_id"],
        limit=int(ctx.get("limit", 100)),
        source_store=ctx.get("source_store", SqlSpendLedgerStore(session)),
        estimated_usd=float(ctx.get("estimated_usd", 0.0)),
        license_checker=ctx.get("license_checker", license_allows_sourcing),
    )


async def verify_lead_emails_job(ctx: dict) -> dict:
    session = ctx["session"]
    return await verify_lead_emails_engine(
        session=session,
        verifier=ctx.get("verifier"),
        lead_email_ids=list(ctx.get("lead_email_ids", [])),
        verifier_store=ctx.get(
            "verifier_store",
            SqlSpendLedgerStore(session),
        ),
        mx_lookup=ctx.get("mx_lookup", DnsMxLookup()),
        risky_share_cap=ctx.get("risky_share_cap"),
    )


async def personalize(ctx: dict) -> dict:
    """Personalize one verified enrollment; never sends or queues implicitly."""
    session = ctx["session"]
    enrollment_id = ctx["enrollment_id"]

    enrollment = await session.get(Enrollment, enrollment_id)
    if enrollment is None:
        return {"paused": False, "human_review": True, "draft": None, "provider_calls": 0}

    campaign = await session.get(Campaign, enrollment.campaign_id)
    lead = await session.get(Lead, enrollment.lead_id)
    lead_email = await session.get(LeadEmail, enrollment.lead_email_id)
    if campaign is None or lead is None or lead_email is None:
        return {"paused": False, "human_review": True, "draft": None, "provider_calls": 0}

    llm = ctx.get("llm")
    if llm is None:
        if not settings.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY is required for personalization")
        llm = GroqLLMClient(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

    return await personalize_enrollment(
        session=session,
        enrollment=enrollment,
        campaign=campaign,
        lead=lead,
        lead_email=lead_email,
        llm=llm,
        research=ctx.get("research", FakeResearchClient()),
        spend_store=ctx.get("spend_store", SqlSpendLedgerStore(session)),
        suppression_store=ctx.get("suppression_store"),
    )
