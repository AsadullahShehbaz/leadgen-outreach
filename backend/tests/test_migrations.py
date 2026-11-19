import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import normalize_database_url, settings
from tests.test_models import EXPECTED_TABLES

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[1]


def get_test_database_url() -> str:
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping migration test")

    test_url = normalize_database_url(settings.test_database_url)
    dev_url = settings.async_database_url

    # Safety check: never run downgrade/base against the development database.
    # Supabase pooler hosts are shared by region, so compare host, username
    # (it contains the project ref) and database name together.
    dev_parts = urlsplit(dev_url)
    test_parts = urlsplit(test_url)
    dev_key = (dev_parts.hostname, dev_parts.username, dev_parts.path)
    test_key = (test_parts.hostname, test_parts.username, test_parts.path)
    if dev_key == test_key:
        pytest.fail(
            "TEST_DATABASE_URL must point to a separate Supabase project, "
            "not the same project as DATABASE_URL"
        )

    return test_url


@pytest.fixture(scope="module")
def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # Alembic's config parser treats "%" specially, and URL-encoded passwords
    # contain it (for example %40 for "@"). Escape and let the parser restore it.
    config.set_main_option(
        "sqlalchemy.url", get_test_database_url().replace("%", "%%")
    )
    return config


async def table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
    finally:
        await engine.dispose()
    return set(names)


def test_upgrade_downgrade_upgrade(alembic_config: Config) -> None:
    database_url = alembic_config.get_main_option("sqlalchemy.url")

    command.upgrade(alembic_config, "head")
    tables = asyncio.run(table_names(database_url))
    assert EXPECTED_TABLES <= tables
    assert "alembic_version" in tables

    command.downgrade(alembic_config, "base")
    tables = asyncio.run(table_names(database_url))
    assert not (EXPECTED_TABLES & tables)

    command.upgrade(alembic_config, "head")
    tables = asyncio.run(table_names(database_url))
    assert EXPECTED_TABLES <= tables
