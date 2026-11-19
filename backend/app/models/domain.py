from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, tz_column


class Domain(TimestampMixin, table=True):
    __tablename__ = "domains"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_domains_workspace_id_name"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, name) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    name: str
    spf_ok: bool = False
    dkim_ok: bool = False
    dmarc_ok: bool = False
    warmup_started_at: datetime | None = Field(default=None, sa_column=tz_column())


class Mailbox(TimestampMixin, table=True):
    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "address", name="uq_mailboxes_workspace_id_address"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, address) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    domain_id: UUID = Field(foreign_key="domains.id", index=True)
    address: str
    daily_cap: int = 40
    status: str = "warming"  # warming | active | paused
    health_score: float = 100.0
