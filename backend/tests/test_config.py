from app.core.config import normalize_database_url


def test_supabase_url_becomes_asyncpg():
    url = (
        "postgresql://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/"
        "postgres?sslmode=require"
    )

    assert normalize_database_url(url) == (
        "postgresql+asyncpg://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/"
        "postgres?ssl=require"
    )


def test_unsupported_parameters_are_removed():
    url = (
        "postgresql://user:pass@host:5432/db"
        "?sslmode=require&channel_binding=require&pgbouncer=true"
    )

    assert normalize_database_url(url) == (
        "postgresql+asyncpg://user:pass@host:5432/db?ssl=require"
    )


def test_plain_and_already_asyncpg_urls():
    assert normalize_database_url("postgres://u:p@h/db") == (
        "postgresql+asyncpg://u:p@h/db"
    )

    already = "postgresql+asyncpg://u:p@h/db?ssl=require"
    assert normalize_database_url(already) == already
