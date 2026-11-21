import asyncio
from dataclasses import dataclass
from datetime import date

import pytest

from app.core.config import Settings
from app.models.analytics import SpendLedger
from app.services.budget.spend_caps import (
    SpendCheck,
    SpendKind,
    SpendLimits,
    SqlSpendLedgerStore,
    check_spend,
    record_usage,
    reserve_usage,
    spend_summary,
)

DAY = date(2026, 11, 21)


@dataclass
class Usage:
    kind: SpendKind
    day: date
    units: int
    est_usd: float


class MemorySpendStore:
    def __init__(self) -> None:
        self.rows: list[Usage] = []
        self.lock = asyncio.Lock()
        self.fail_reads = False

    async def sum_units(self, kind: SpendKind, start_day: date, end_day: date) -> int:
        if self.fail_reads:
            raise RuntimeError("store unavailable")
        return sum(
            row.units
            for row in self.rows
            if row.kind == kind and start_day <= row.day <= end_day
        )

    async def sum_usd(self, kind: SpendKind, start_day: date, end_day: date) -> float:
        if self.fail_reads:
            raise RuntimeError("store unavailable")
        return sum(
            row.est_usd
            for row in self.rows
            if row.kind == kind and start_day <= row.day <= end_day
        )

    async def add_usage(
        self, kind: SpendKind, day: date, units: int, est_usd: float
    ) -> None:
        self.rows.append(Usage(kind, day, units, est_usd))

    async def reserve_usage(
        self,
        kind: SpendKind,
        day: date,
        units: int,
        est_usd: float,
        limits: SpendLimits,
    ) -> SpendCheck:
        async with self.lock:
            check = await check_spend(
                self, kind, limits, units, est_usd, day
            )
            if check.allowed:
                await self.add_usage(kind, day, units, est_usd)
                return await check_spend(self, kind, limits, 0, 0.0, day)
            return check


@pytest.fixture
def limits() -> SpendLimits:
    return SpendLimits(
        llm_usd_per_day=5.0,
        verify_units_per_day=10,
        source_units_per_day=20,
    )


@pytest.mark.asyncio
async def test_zero_limit_disables_paid_step():
    store = MemorySpendStore()
    limits = SpendLimits(0.0, 0, 0)

    for kind in ("llm", "verify", "source"):
        result = await check_spend(store, kind, limits, day=DAY)
        assert result.allowed is False


@pytest.mark.asyncio
async def test_verification_cap_allows_exact_boundary_and_denies_overage(limits):
    store = MemorySpendStore()
    await record_usage(store, "verify", 8, 0.0, DAY)

    allowed = await check_spend(store, "verify", limits, requested_units=2, day=DAY)
    denied = await check_spend(store, "verify", limits, requested_units=3, day=DAY)

    assert allowed.allowed is True
    assert denied.allowed is False


@pytest.mark.asyncio
async def test_source_cap_uses_units(limits):
    store = MemorySpendStore()
    await record_usage(store, "source", 18, 12.5, DAY)

    result = await check_spend(
        store, "source", limits, requested_units=3, requested_usd=100.0, day=DAY
    )

    assert result.allowed is False
    assert result.limit_units == 20


@pytest.mark.asyncio
async def test_llm_cap_uses_estimated_usd_and_keeps_units(limits):
    store = MemorySpendStore()
    await record_usage(store, "llm", 1000, 4.25, DAY)

    allowed = await check_spend(
        store, "llm", limits, requested_units=500, requested_usd=0.75, day=DAY
    )
    denied = await check_spend(
        store, "llm", limits, requested_units=1, requested_usd=0.76, day=DAY
    )

    assert allowed.allowed is True
    assert allowed.used_units == 1000
    assert allowed.used_usd == 4.25
    assert allowed.limit_usd == 5.0
    assert denied.allowed is False


@pytest.mark.asyncio
async def test_cap_check_does_not_record_but_record_usage_adds_one_row(limits):
    store = MemorySpendStore()

    await check_spend(store, "verify", limits, day=DAY)
    assert store.rows == []

    await record_usage(store, "verify", 1, 0.02, DAY)
    assert store.rows == [Usage("verify", DAY, 1, 0.02)]


@pytest.mark.asyncio
async def test_concurrent_reservations_do_not_exceed_cap(limits):
    store = MemorySpendStore()

    results = await asyncio.gather(
        *(
            reserve_usage(store, "verify", limits, requested_units=1, day=DAY)
            for _ in range(25)
        )
    )

    assert sum(result.allowed for result in results) == 10
    assert await store.sum_units("verify", DAY, DAY) == 10


@pytest.mark.asyncio
async def test_reservation_counts_toward_llm_cost_cap(limits):
    store = MemorySpendStore()

    result = await reserve_usage(
        store, "llm", limits, requested_units=50, requested_usd=2.5, day=DAY
    )
    denied = await reserve_usage(
        store, "llm", limits, requested_units=50, requested_usd=2.51, day=DAY
    )

    assert result.allowed is True
    assert result.used_usd == 2.5
    assert denied.allowed is False
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_invalid_kind_and_usage_values_raise(limits):
    store = MemorySpendStore()

    with pytest.raises(ValueError, match="unsupported spend kind"):
        await check_spend(store, "mail", limits, day=DAY)
    with pytest.raises(ValueError, match="units"):
        await record_usage(store, "verify", -1, 0.0, DAY)
    with pytest.raises(ValueError, match="estimated USD"):
        await record_usage(store, "llm", 1, float("inf"), DAY)
    with pytest.raises(ValueError, match="units"):
        await check_spend(store, "source", limits, requested_units=True, day=DAY)


@pytest.mark.asyncio
async def test_invalid_limits_raise():
    store = MemorySpendStore()

    with pytest.raises(ValueError, match="estimated USD"):
        await check_spend(store, "llm", SpendLimits(float("nan"), 1, 1), day=DAY)
    with pytest.raises(ValueError, match="units"):
        await check_spend(store, "verify", SpendLimits(1.0, -1, 1), day=DAY)


@pytest.mark.asyncio
async def test_store_failure_is_not_swallowed_and_paid_action_does_not_start(limits):
    store = MemorySpendStore()
    store.fail_reads = True
    paid_action_started = False

    with pytest.raises(RuntimeError, match="store unavailable"):
        result = await check_spend(store, "llm", limits, day=DAY)
        if result.allowed:
            paid_action_started = True

    assert paid_action_started is False


@pytest.mark.asyncio
async def test_summary_uses_day_and_month_to_date(limits):
    store = MemorySpendStore()
    await record_usage(store, "llm", 10, 0.5, date(2026, 10, 31))
    await record_usage(store, "llm", 20, 1.25, date(2026, 11, 1))
    await record_usage(store, "llm", 30, 2.0, DAY)
    await record_usage(store, "llm", 40, 4.0, date(2026, 11, 22))

    result = await spend_summary(store, "llm", DAY)

    assert result == {
        "kind": "llm",
        "today_units": 30,
        "today_est_usd": 2.0,
        "month_units": 50,
        "month_est_usd": 3.25,
    }


def test_settings_load_spend_caps_and_reject_invalid_values():
    config = Settings(
        _env_file=None,
        MAX_LLM_USD_PER_DAY=12.5,
        MAX_VERIFICATIONS_PER_DAY=300,
        MAX_SOURCE_CREDITS_PER_DAY=50,
    )
    assert config.MAX_LLM_USD_PER_DAY == 12.5
    assert config.MAX_VERIFICATIONS_PER_DAY == 300
    assert config.MAX_SOURCE_CREDITS_PER_DAY == 50

    with pytest.raises(ValueError):
        Settings(_env_file=None, MAX_LLM_USD_PER_DAY=float("inf"))
    with pytest.raises(ValueError):
        Settings(_env_file=None, MAX_SOURCE_CREDITS_PER_DAY=-1)


class FakeResult:
    def __init__(self, totals=(3, 1.25)):
        self.totals = totals

    def one(self):
        return self.totals


class FakeSqlSession:
    def __init__(self, use_added_totals=False):
        self.statements = []
        self.added = []
        self.flushed = 0
        self.use_added_totals = use_added_totals

    async def execute(self, statement):
        self.statements.append(statement)
        if "pg_advisory_xact_lock" in str(statement):
            return FakeResult((0, 0.0))
        if not self.use_added_totals:
            return FakeResult()
        return FakeResult(
            (
                sum(row.units for row in self.added),
                sum(row.est_usd for row in self.added),
            )
        )

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_sql_store_aggregates_and_adds_usage():
    session = FakeSqlSession()
    store = SqlSpendLedgerStore(session)

    assert await store.sum_units("verify", DAY, DAY) == 3
    assert await store.sum_usd("verify", DAY, DAY) == 1.25
    await store.add_usage("verify", DAY, 2, 0.1)

    assert len(session.statements) == 2
    assert all("spend_ledger" in str(statement) for statement in session.statements)
    assert isinstance(session.added[0], SpendLedger)
    assert session.added[0].day == DAY
    assert session.added[0].kind == "verify"
    assert session.added[0].units == 2
    assert session.added[0].est_usd == 0.1
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_sql_reservation_uses_postgres_advisory_lock_and_denied_calls_write_nothing():
    session = FakeSqlSession(use_added_totals=True)
    store = SqlSpendLedgerStore(session)
    limits = SpendLimits(5.0, 3, 20)

    allowed = await store.reserve_usage("verify", DAY, 2, 0.1, limits)
    denied = await store.reserve_usage("verify", DAY, 2, 0.1, limits)

    assert "pg_advisory_xact_lock" in str(session.statements[0])
    assert allowed.allowed is True
    assert denied.allowed is False
    assert len(session.added) == 1
