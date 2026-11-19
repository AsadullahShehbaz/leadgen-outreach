from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# One engine for the whole app. It connects lazily on first use.
engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)

# expire_on_commit=False keeps objects usable after commit, which is handy
# inside background jobs.
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that gives each request its own session."""
    async with Session() as session:
        yield session
