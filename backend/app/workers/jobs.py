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
