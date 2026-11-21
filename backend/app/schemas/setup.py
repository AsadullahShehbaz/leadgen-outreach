from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SetupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialized: bool
    admin_created: bool
    workspace_created: bool
    license_stored: bool
    llm_configured: bool
    verifier_configured: bool
    sender_configured: bool
    responsibility_accepted: bool
    complete: bool


class SetupAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    password: str = Field(min_length=12)


class SetupAdminResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    user_id: UUID
    email: str
    role: str


class SetupWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    sender_identity: str = Field(min_length=1)
    postal_address: str = Field(min_length=1)
    timezone: str = "UTC"
    accept_responsibility: bool


class SetupLicenseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license_token: str = Field(min_length=1)


class SetupLicenseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stored: bool
    valid: bool = True
    in_grace: bool = False
    expires_at: datetime | None = None


class SetupConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    secret: dict[str, Any]


class SetupConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    status: str


class SetupDomainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)


class SetupDomainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    spf_ok: bool
    dkim_ok: bool
    dmarc_ok: bool


class SetupMailboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: UUID
    address: str = Field(min_length=3)
    daily_cap: int = Field(default=40, ge=1)


class SetupMailboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    address: str
    daily_cap: int
    status: str
