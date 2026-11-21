from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Literal, Protocol, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.models.analytics import SpendLedger

SpendKind = Literal["llm", "verify", "source"]


class SpendLedgerStore(Protocol):
    async def sum_units(self, kind: SpendKind, start_day: date, end_day: date) -> int:
        ...

    async def sum_usd(self, kind: SpendKind, start_day: date, end_day: date) -> float:
        ...

    async def add_usage(
        self,
        kind: SpendKind,
        day: date,
        units: int,
        est_usd: float,
    ) -> None:
        ...


class AtomicSpendLedgerStore(SpendLedgerStore, Protocol):
    async def reserve_usage(
        self,
        kind: SpendKind,
        day: date,
        units: int,
        est_usd: float,
        limits: "SpendLimits",
    ) -> "SpendCheck":
        ...


@dataclass(frozen=True)
class SpendLimits:
    llm_usd_per_day: float
    verify_units_per_day: int
    source_units_per_day: int

    @classmethod
    def from_settings(cls, config: Settings = settings) -> "SpendLimits":
        return cls(
            llm_usd_per_day=config.MAX_LLM_USD_PER_DAY,
            verify_units_per_day=config.MAX_VERIFICATIONS_PER_DAY,
            source_units_per_day=config.MAX_SOURCE_CREDITS_PER_DAY,
        )


@dataclass(frozen=True)
class SpendCheck:
    allowed: bool
    kind: SpendKind
    used_units: int
    limit_units: int
    used_usd: float
    limit_usd: float | None = None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _validate_kind(kind: str) -> SpendKind:
    if not isinstance(kind, str) or kind not in {"llm", "verify", "source"}:
        raise ValueError(f"unsupported spend kind: {kind!r}")
    return cast(SpendKind, kind)


def _validate_units(units: int) -> None:
    if isinstance(units, bool) or not isinstance(units, int) or units < 0:
        raise ValueError("units must be a non-negative integer")


def _validate_usd(amount: float) -> None:
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError("estimated USD must be a finite non-negative number")
    if not isfinite(amount) or amount < 0:
        raise ValueError("estimated USD must be a finite non-negative number")


def _validate_limits(limits: SpendLimits) -> None:
    _validate_usd(limits.llm_usd_per_day)
    _validate_units(limits.verify_units_per_day)
    _validate_units(limits.source_units_per_day)


def _make_check(
    kind: SpendKind,
    limits: SpendLimits,
    used_units: int,
    used_usd: float,
    requested_units: int,
    requested_usd: float,
) -> SpendCheck:
    if kind == "llm":
        limit_usd = limits.llm_usd_per_day
        allowed = limit_usd > 0 and used_usd + requested_usd <= limit_usd
        return SpendCheck(
            allowed=allowed,
            kind=kind,
            used_units=used_units,
            limit_units=0,
            used_usd=used_usd,
            limit_usd=limit_usd,
        )

    limit_units = (
        limits.verify_units_per_day if kind == "verify" else limits.source_units_per_day
    )
    return SpendCheck(
        allowed=limit_units > 0 and used_units + requested_units <= limit_units,
        kind=kind,
        used_units=used_units,
        limit_units=limit_units,
        used_usd=used_usd,
    )


async def check_spend(
    store: SpendLedgerStore,
    kind: SpendKind,
    limits: SpendLimits,
    requested_units: int = 1,
    requested_usd: float = 0.0,
    day: date | None = None,
) -> SpendCheck:
    """Read the current cap state; use reserve_usage before concurrent paid work."""
    kind = _validate_kind(kind)
    _validate_limits(limits)
    _validate_units(requested_units)
    _validate_usd(requested_usd)
    usage_day = day or utc_today()

    used_units = await store.sum_units(kind, usage_day, usage_day)
    used_usd = await store.sum_usd(kind, usage_day, usage_day)
    return _make_check(
        kind, limits, used_units, used_usd, requested_units, requested_usd
    )


async def record_usage(
    store: SpendLedgerStore,
    kind: SpendKind,
    units: int,
    est_usd: float,
    day: date | None = None,
) -> None:
    """Record completed usage when the caller does not need an atomic reservation."""
    kind = _validate_kind(kind)
    _validate_units(units)
    _validate_usd(est_usd)
    await store.add_usage(kind, day or utc_today(), units, est_usd)


async def reserve_usage(
    store: AtomicSpendLedgerStore,
    kind: SpendKind,
    limits: SpendLimits,
    requested_units: int = 1,
    requested_usd: float = 0.0,
    day: date | None = None,
) -> SpendCheck:
    """Atomically enforce the cap and reserve estimated usage before paid work.

    The store's transaction must be committed before starting the external call.
    A reservation is counted conservatively as usage; do not record it a second time.
    """
    kind = _validate_kind(kind)
    _validate_limits(limits)
    _validate_units(requested_units)
    _validate_usd(requested_usd)
    return await store.reserve_usage(
        kind,
        day or utc_today(),
        requested_units,
        requested_usd,
        limits,
    )


async def spend_summary(
    store: SpendLedgerStore,
    kind: SpendKind,
    day: date,
) -> dict[str, int | float | str]:
    kind = _validate_kind(kind)
    first_of_month = day.replace(day=1)
    return {
        "kind": kind,
        "today_units": await store.sum_units(kind, day, day),
        "today_est_usd": await store.sum_usd(kind, day, day),
        "month_units": await store.sum_units(kind, first_of_month, day),
        "month_est_usd": await store.sum_usd(kind, first_of_month, day),
    }


class SqlSpendLedgerStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _totals(self, kind: SpendKind, start_day: date, end_day: date) -> tuple[int, float]:
        statement = select(
            func.coalesce(func.sum(SpendLedger.units), 0),
            func.coalesce(func.sum(SpendLedger.est_usd), 0.0),
        ).where(
            SpendLedger.kind == kind,
            SpendLedger.day >= start_day,
            SpendLedger.day <= end_day,
        )
        result = await self.session.execute(statement)
        units, est_usd = result.one()
        return int(units), float(est_usd)

    async def sum_units(self, kind: SpendKind, start_day: date, end_day: date) -> int:
        units, _ = await self._totals(kind, start_day, end_day)
        return units

    async def sum_usd(self, kind: SpendKind, start_day: date, end_day: date) -> float:
        _, est_usd = await self._totals(kind, start_day, end_day)
        return est_usd

    async def add_usage(
        self,
        kind: SpendKind,
        day: date,
        units: int,
        est_usd: float,
    ) -> None:
        self.session.add(
            SpendLedger(day=day, kind=kind, units=units, est_usd=est_usd)
        )
        await self.session.flush()

    async def reserve_usage(
        self,
        kind: SpendKind,
        day: date,
        units: int,
        est_usd: float,
        limits: SpendLimits,
    ) -> SpendCheck:
        kind = _validate_kind(kind)
        _validate_limits(limits)
        _validate_units(units)
        _validate_usd(est_usd)

        # Serialize reservations for the same kind and UTC day, including the first row.
        lock_key = f"leadgen-spend:{kind}:{day.isoformat()}"
        await self.session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(lock_key, 0)
                )
            )
        )
        used_units, used_usd = await self._totals(kind, day, day)
        check = _make_check(kind, limits, used_units, used_usd, units, est_usd)
        if check.allowed:
            self.session.add(
                SpendLedger(day=day, kind=kind, units=units, est_usd=est_usd)
            )
            await self.session.flush()
            return _make_check(
                kind,
                limits,
                used_units + units,
                used_usd + est_usd,
                0,
                0.0,
            )
        return check
