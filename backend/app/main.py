from fastapi import FastAPI, Response
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import engine
from app.core.redis import get_redis
from app.core.config import settings
from app.routers.auth import router as auth_router
from app.routers.setup import router as setup_router
from app.routers.system import router as system_router
from app.routers.connections import router as connections_router
from app.routers.domains import router as domains_router
from app.routers.mailboxes import router as mailboxes_router
from app.routers.campaigns import router as campaigns_router
from app.routers.leads import router as leads_router
from app.routers.inbox import router as inbox_router
from app.routers.analytics import router as analytics_router
from app.routers.compliance import router as compliance_router

app = FastAPI(title="LeadGen Agent")
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(system_router)
app.include_router(connections_router)
app.include_router(domains_router)
app.include_router(mailboxes_router)
app.include_router(campaigns_router)
app.include_router(leads_router)
app.include_router(inbox_router)
app.include_router(analytics_router)
app.include_router(compliance_router)


@app.get("/health")
async def health(response: Response):
    checks = {"database": "ok", "redis": "ok"}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        checks["database"] = "unavailable"

    redis = get_redis(settings.redis_url)
    try:
        await redis.ping()
    except (RedisError, OSError):
        checks["redis"] = "unavailable"
    finally:
        await redis.aclose()

    if "unavailable" in checks.values():
        response.status_code = 503
        return {"status": "unhealthy", "checks": checks}

    return {"status": "ok", "checks": checks}
