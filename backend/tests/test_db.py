from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import Session


def test_session_uses_sqlmodel_async_session():
    # Routers and services call session.exec(), which SQLAlchemy's plain
    # AsyncSession does not provide.
    assert Session.class_ is AsyncSession
    assert hasattr(AsyncSession, "exec")
