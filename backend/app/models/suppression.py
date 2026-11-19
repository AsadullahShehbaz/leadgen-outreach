from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlmodel import Field

from app.models.base import TimestampMixin, utcnow


class Suppression(TimestampMixin, table=True):
    __tablename__ = "suppression"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Hashed so the database never stores a plain suppression address.
    email_hash: str = Field(unique=True, index=True)
    domain: str | None = None
    reason: str
    at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
