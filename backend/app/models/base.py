from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# Stable names for primary keys, foreign keys, uniques and indexes.
# Without this, Alembic creates random constraint names and future
# migrations become noisy.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def apply_naming_convention() -> None:
    # Must run before any table class is created (see app/models/__init__.py).
    SQLModel.metadata.naming_convention = NAMING_CONVENTION


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    """Adds a UTC created_at column to every table."""

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


def jsonb_column(default_sql: str = "'{}'::jsonb") -> Column[Any]:
    # JSONB holds flexible per-record data (raw source payloads, campaign
    # product/ICP, experiment variants). The server default keeps raw SQL
    # inserts valid too.
    return Column(JSONB, nullable=False, default=dict, server_default=text(default_sql))


def tz_column(*, nullable: bool = True) -> Column[Any]:
    """A timezone-aware timestamp column stored in UTC."""
    return Column(DateTime(timezone=True), nullable=nullable)
