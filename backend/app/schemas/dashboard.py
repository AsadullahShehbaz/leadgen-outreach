from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SequenceStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_no: int = Field(ge=1)
    delay_days: int = Field(default=3, ge=0)
    angle_hint: str | None = None


class CampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    product: dict[str, Any] = Field(default_factory=dict)
    icp: dict[str, Any] = Field(default_factory=dict)
    compliance_mode: Literal["standard", "strict"] = "standard"
    require_approval: bool = True
    sequence_steps: list[SequenceStepRequest] = Field(default_factory=list)


class CampaignResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    product: dict[str, Any]
    icp: dict[str, Any]
    status: str
    compliance_mode: str
    require_approval: bool
    sequence_steps: list[SequenceStepRequest]


class LeadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    company_name: str | None
    company_domain: str | None
    person_name: str | None
    title: str | None
    country: str | None
    icp_score: float | None
    lawful_basis: str | None
    verify_status: str


class CsvImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_text: str = Field(min_length=1)


class DraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    status: str
    subject: str | None
    body: str | None
    claims: list[str]


class InboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    direction: str
    message_id: str | None
    subject: str
    body: str
    sent_at: datetime | None
    enrollment_id: UUID
    reply_class: str | None = None


class SuppressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    reason: str = Field(min_length=1)


class SuppressionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_hash: str
    domain: str | None
    reason: str
    at: datetime


class ComplianceSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_identity: str = Field(min_length=1)
    postal_address: str = Field(min_length=1)
    footer_text: str | None = None
    timezone: str = "UTC"
