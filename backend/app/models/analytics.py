from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column


class Experiment(TimestampMixin, table=True):
    __tablename__ = "experiments"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    campaign_id: UUID = Field(foreign_key="campaigns.id", index=True)
    kind: str
    variants: dict = Field(default_factory=dict, sa_column=jsonb_column())
    stats: dict = Field(default_factory=dict, sa_column=jsonb_column())


class SpendLedger(TimestampMixin, table=True):
    __tablename__ = "spend_ledger"
    __table_args__ = (Index("ix_spend_ledger_day_kind", "day", "kind"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    day: date
    kind: str  # llm | verify | source
    units: int = 0
    est_usd: float = 0.0
