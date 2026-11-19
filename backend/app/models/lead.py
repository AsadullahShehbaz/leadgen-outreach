from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column, tz_column, utcnow


class Lead(TimestampMixin, table=True):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_workspace_id_company_domain", "workspace_id", "company_domain"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the composite (workspace_id, company_domain) index below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    source: str
    company_domain: str | None = None
    company_name: str | None = None
    person_name: str | None = None
    title: str | None = None
    country: str | None = None
    icp_score: float | None = None
    lawful_basis: str | None = None
    collected_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    raw: dict = Field(default_factory=dict, sa_column=jsonb_column())


class LeadEmail(TimestampMixin, table=True):
    __tablename__ = "lead_emails"
    __table_args__ = (
        UniqueConstraint("lead_id", "email", name="uq_lead_emails_lead_id_email"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (lead_id, email) constraint below.
    lead_id: UUID = Field(foreign_key="leads.id")
    email: str = Field(index=True)
    verify_status: str = "unknown"  # valid | risky | invalid | unknown
    verified_at: datetime | None = Field(default=None, sa_column=tz_column())
    role_based: bool = False
