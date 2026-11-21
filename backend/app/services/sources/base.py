from typing import Protocol

from pydantic import BaseModel, Field


class RawLead(BaseModel):
    company_name: str | None = None
    company_domain: str | None = None
    person_name: str | None = None
    title: str | None = None
    email: str | None = None
    country: str | None = None
    lawful_basis: str | None = None
    source: str
    raw: dict = Field(default_factory=dict)


class LeadSource(Protocol):
    name: str

    async def fetch(self, query: dict, limit: int) -> list[RawLead]:
        ...
