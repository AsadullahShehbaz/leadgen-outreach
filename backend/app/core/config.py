from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Turn a plain Postgres URL into one asyncpg can use.

    Supabase gives URLs like:
        postgresql://user:pass@host:5432/postgres?sslmode=require&channel_binding=require

    asyncpg does not understand "sslmode" or "channel_binding", so we rewrite
    the scheme and the query string before passing it to SQLAlchemy.
    """
    url = url.strip()

    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in ("channel_binding", "pgbouncer"):
            continue
        if key == "sslmode":
            key = "ssl"
        query.append((key, value))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Placeholder so the app can start before .env exists.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Used only by the migration integration test.
    test_database_url: str | None = None

    @property
    def async_database_url(self) -> str:
        return normalize_database_url(self.database_url)


settings = Settings()
