from math import isfinite
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
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
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str | None = None
    SENDING_ENABLED: bool = False
    PUBLIC_URL: str = "http://localhost"
    SECRET_KEY: str = "local-development-secret-key-change-me-32bytes"
    FERNET_KEY: str | None = None
    LICENSE_PUBLIC_KEY_PEM: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Used only by the migration integration test.
    test_database_url: str | None = None
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_API_KEY: str | None = None
    LLM_MODEL_SMALL: str = "llama-3.1-8b-instant"
    LLM_MODEL_LARGE: str = "llama-3.3-70b-versatile"

    send_window_start_hour: int = 9
    send_window_end_hour: int = 17
    send_window_days: str = "1,2,3,4,5"
    test_redis_url: str | None = None
    MAX_LLM_USD_PER_DAY: float = 0.0
    MAX_VERIFICATIONS_PER_DAY: int = 0
    MAX_SOURCE_CREDITS_PER_DAY: int = 0

    @field_validator("MAX_LLM_USD_PER_DAY")
    @classmethod
    def validate_llm_daily_limit(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("MAX_LLM_USD_PER_DAY must be a finite non-negative number")
        return value

    @field_validator("MAX_VERIFICATIONS_PER_DAY", "MAX_SOURCE_CREDITS_PER_DAY")
    @classmethod
    def validate_daily_unit_limit(cls, value: int) -> int:
        if value < 0:
            raise ValueError("daily spend limits must be non-negative")
        return value

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def async_database_url(self) -> str:
        return normalize_database_url(self.database_url)


settings = Settings()
