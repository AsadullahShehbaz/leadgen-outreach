from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TimestampMixin, tz_column


class LicenseState(TimestampMixin, table=True):
    __tablename__ = "license_state"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    token: str = Field(sa_column=Column(Text, nullable=False))
    valid_until: datetime | None = Field(default=None, sa_column=tz_column())
    last_checked_at: datetime | None = Field(default=None, sa_column=tz_column())
