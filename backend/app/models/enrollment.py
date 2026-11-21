from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Text, UniqueConstraint, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column, tz_column, utcnow


class Enrollment(TimestampMixin, table=True):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "lead_id", name="uq_enrollments_campaign_id_lead_id"
        ),
        Index("ix_enrollments_status_next_send_at", "status", "next_send_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (campaign_id, lead_id) constraint below.
    campaign_id: UUID = Field(foreign_key="campaigns.id")
    lead_id: UUID = Field(foreign_key="leads.id", index=True)
    lead_email_id: UUID = Field(foreign_key="lead_emails.id", index=True)
    # Assigned when the first email is sent and reused for follow-ups.
    mailbox_id: UUID | None = Field(default=None, foreign_key="mailboxes.id", index=True)
    status: str = "new"
    step_no: int = 0
    next_send_at: datetime | None = Field(default=None, sa_column=tz_column())
    variant_id: str | None = None
    draft: dict | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )


class Message(TimestampMixin, table=True):
    __tablename__ = "messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    enrollment_id: UUID = Field(foreign_key="enrollments.id", index=True)
    direction: str  # out | in
    message_id: str | None = Field(default=None, index=True)
    in_reply_to: str | None = None
    thread_id: str | None = None
    subject: str
    body: str = Field(sa_column=Column(Text, nullable=False))
    variant_id: str | None = None
    sent_at: datetime | None = Field(default=None, sa_column=tz_column())


class Event(TimestampMixin, table=True):
    __tablename__ = "events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    enrollment_id: UUID = Field(foreign_key="enrollments.id", index=True)
    type: str
    payload: dict = Field(default_factory=dict, sa_column=jsonb_column())
    at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
