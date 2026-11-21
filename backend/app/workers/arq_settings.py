from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.core.redis import get_redis
from app.services.mail.fake import FakeMailProvider
from app.workers.jobs import (
    poll_inbox,
    personalize,
    send_due,
    source_leads,
    verify_lead_emails_job,
)


async def startup(ctx: dict) -> None:
    ctx["redis"] = get_redis(settings.redis_url)
    ctx["mail"] = FakeMailProvider()


async def shutdown(ctx: dict) -> None:
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    functions = [send_due, poll_inbox, source_leads, verify_lead_emails_job, personalize]
    cron_jobs = [
        cron(send_due, minute=set(range(60)), unique=True),
        cron(poll_inbox, minute=set(range(0, 60, 3)), unique=True),
    ]
