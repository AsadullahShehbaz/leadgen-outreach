from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, utcnow


class Workspace(TimestampMixin, table=True):
    __tablename__ = "workspaces"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    sender_identity: str | None = None
    postal_address: str | None = None
    footer_text: str | None = None
    timezone: str = "UTC"
    setup_responsibility_accepted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    setup_completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


class User(TimestampMixin, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_users_workspace_id_email"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, email) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    email: str
    password_hash: str
    role: str = "admin"
    totp_secret: str | None = None
