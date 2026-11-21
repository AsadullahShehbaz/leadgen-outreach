import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from app.models import LeadEmail
from app.services.budget.spend_caps import (
    SpendLimits,
    check_spend,
)
from app.services.sources.base import RawLead
from app.services.sources.fake import FakeLeadSource
from app.services.sources.pipeline import source_leads
from app.services.verify.base import VerifyResult
from app.services.verify.fake import FakeVerifier
from app.services.verify.mx import FakeMxLookup
from app.services.verify.pipeline import verify_lead_email


@dataclass
class Usage:
    kind: str
    day: date
    units: int
    est_usd: float


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list[Usage] = []
        self.lock = asyncio.Lock()

    async def sum_units(self, kind, start_day, end_day):
        return sum(
            row.units
            for row in self.rows
            if row.kind == kind and start_day <= row.day <= end_day
        )

    async def sum_usd(self, kind, start_day, end_day):
        return sum(
            row.est_usd
            for row in self.rows
            if row.kind == kind and start_day <= row.day <= end_day
        )

    async def reserve_usage(self, kind, day, units, est_usd, limits):
        async with self.lock:
            check = await check_spend(
                self,
                kind,
                limits,
                units,
                est_usd,
                day,
            )
            if check.allowed:
                self.rows.append(Usage(kind, day, units, est_usd))
                return await check_spend(self, kind, limits, 0, 0.0, day)
            return check


class FakeCommitSession:
    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_source_cap_hit_pauses_without_provider_call(monkeypatch):
    monkeypatch.setattr(
        "app.services.sources.pipeline.SpendLimits.from_settings",
        lambda: SpendLimits(0.0, 0, 0),
    )
    store = MemoryStore()
    source = FakeLeadSource([RawLead(company_name="Acme", source="fake")])

    result = await source_leads(
        FakeCommitSession(),
        source,
        {},
        "00000000-0000-0000-0000-000000000001",
        10,
        store,
    )

    assert result["paused"] is True
    assert source.calls == []
    assert store.rows == []


@pytest.mark.asyncio
async def test_verification_cap_hit_does_not_call_verifier(monkeypatch):
    monkeypatch.setattr(
        "app.services.verify.pipeline.SpendLimits.from_settings",
        lambda: SpendLimits(0.0, 0, 0),
    )
    store = MemoryStore()
    verifier = FakeVerifier(
        result=VerifyResult(status="valid", reason="confirmed")
    )
    lead_email = LeadEmail(
        lead_id="00000000-0000-0000-0000-000000000002",
        email="person@example.com",
    )

    class Session:
        async def get(self, model, id):
            return lead_email

        async def commit(self):
            return None

    result = await verify_lead_email(
        Session(),
        lead_email.id,
        verifier,
        store,
        FakeMxLookup(True),
    )

    assert result["paused"] is True
    assert verifier.calls == []
