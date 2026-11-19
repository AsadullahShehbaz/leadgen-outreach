from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column


class Campaign(TimestampMixin, table=True):
    __tablename__ = "campaigns"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    name: str
    product: dict = Field(default_factory=dict, sa_column=jsonb_column())
    icp: dict = Field(default_factory=dict, sa_column=jsonb_column())
    status: str = "draft"
    compliance_mode: str = "standard"
    require_approval: bool = True


class SequenceStep(TimestampMixin, table=True):
    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "step_no", name="uq_sequence_steps_campaign_id_step_no"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (campaign_id, step_no) constraint below.
    campaign_id: UUID = Field(foreign_key="campaigns.id")
    step_no: int
    delay_days: int = 3
    angle_hint: str | None = None
