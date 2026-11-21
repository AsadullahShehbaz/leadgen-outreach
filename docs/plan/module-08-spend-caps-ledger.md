# Module 8 Plan - Spend Caps + Ledger

Status: planned (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 10, 13, 20-22
(module 8).
Acceptance test from the design: **a cap hit pauses the step**.

## Goal

Implement a small, beginner-friendly budget gate for paid vendor usage:

1. Add three environment-backed daily limits: LLM, verification, and source credits.
2. Add a spend-ledger interface and a Postgres-backed implementation.
3. Check the daily limit before each paid call.
4. Record the actual or estimated units and estimated USD cost after a successful call.
5. Return a clear cap result so the caller can pause the relevant job or workflow step.
6. Provide small summary helpers for today's and month-to-date spend estimates.

This module protects future sourcing, verification, and LLM work. It does not
implement those jobs themselves.

## Out of scope

- LeadSource, Verifier, and LLM provider implementations. Those remain Modules 9-10.
- Live vendor billing or vendor-account balance reads.
- HTTP dashboard or analytics endpoints. Module 13 owns the React dashboard.
- License enforcement. Module 11 owns license checks.
- Redis-based spend reservation. This module must not change the Redis send limiter.
- Spend metering for outbound email sending. Email sends are not in the ledger kinds.
- Automatic retries or automatic pausing of suppression and inbox-compliance work.
- Currency conversion, invoicing, or provider billing reconciliation.

## Decisions

| Question | Decision |
|---|---|
| Ledger kinds | Only `llm`, `verify`, and `source`, matching the existing `SpendLedger.kind` column. |
| Ledger granularity | One row per call or batch usage event. No pre-aggregation is required in this module. |
| Daily key | UTC calendar date. Use `date.today()` only in a single pure function boundary; callers pass an explicit date for tests. |
| Monthly summary | UTC month to date, from the first calendar day through the supplied UTC date. |
| Cap check | Fail closed on an unknown kind or invalid limit. A cap hit returns `allowed=false`; it does not raise for normal limit conditions. |
| Atomicity | Check and reserve usage atomically in the database-backed implementation. Concurrent calls must not allow the total to exceed the daily limit. |
| Reservations | Module 8 records usage after a call. A reservation is optional and may be added only if later modules need crash-safe pre-metering. |
| Estimated costs | Store caller-supplied `est_usd`; never invent or fetch vendor prices. |
| Units | Units are caller-supplied non-negative integers. LLM use may be token units or a cost model chosen by Module 10; verification/source use is provider units. |
| Cap hit behavior | Return a `SpendCapHit` result and require the caller to pause that step and raise a dashboard alert. No state-machine status change is made here. |
| Compliance independence | Spend failures may pause sourcing, verification, and personalization only. They never block suppression, bounce handling, unsubscribe handling, or sends. |
| Redis | No Redis dependency is required. |
| Migration | No migration is required for the existing `SpendLedger` model if the implementation uses `day`, `kind`, `units`, and `est_usd`. |

## Deliverables

```text
backend/
  app/core/
    config.py                # update: spend cap settings
  app/services/
    budget/
      __init__.py            # NEW package
      spend_caps.py          # NEW: caps, ledger gate, summaries
  tests/
    test_spend_caps.py       # NEW
docs/plan/
  module-08-spend-caps-ledger.md
PROGRESS.md
README.md
```

Update `backend/.env.example` with empty or safe local defaults for:

- `MAX_LLM_USD_PER_DAY`
- `MAX_VERIFICATIONS_PER_DAY`
- `MAX_SOURCE_CREDITS_PER_DAY`

No frontend files or API router are added in this module.

## Settings

Add these values to `Settings`:

```python
MAX_LLM_USD_PER_DAY: float = 0.0
MAX_VERIFICATIONS_PER_DAY: int = 0
MAX_SOURCE_CREDITS_PER_DAY: int = 0
```

Interpret zero conservatively:

- `0` means the corresponding paid step is disabled until a positive limit is configured.
- Negative values are invalid and must fail closed.
- Non-finite values are invalid and must fail closed.

Keep existing behavior for modules not yet using spend gates: this module only
exports helpers. It must not silently change live send behavior.

## Spend API

Use a small protocol so tests do not need Postgres:

```python
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
```

Use explicit data types:

```python
@dataclass(frozen=True)
class SpendLimits:
    llm_usd_per_day: float
    verify_units_per_day: int
    source_units_per_day: int


@dataclass(frozen=True)
class SpendCheck:
    allowed: bool
    kind: SpendKind
    used_units: int
    limit_units: int
    used_usd: float
    limit_usd: float | None = None
```

The implementation may split `llm`, verification, and source helpers rather than
forcing a large generic class.

### Core functions

```python
async def check_spend(
    store: SpendLedgerStore,
    kind: SpendKind,
    limits: SpendLimits,
    requested_units: int = 1,
    requested_usd: float = 0.0,
    day: date | None = None,
) -> SpendCheck:
    ...


async def record_usage(
    store: SpendLedgerStore,
    kind: SpendKind,
    units: int,
    est_usd: float,
    day: date | None = None,
) -> None:
    ...


async def spend_summary(
    store: SpendLedgerStore,
    kind: SpendKind,
    day: date,
) -> dict:
    ...
```

Behavior:

- Reject blank or unknown kinds.
- Reject negative or non-finite units/USD values.
- For `llm`, enforce estimated USD daily spend. The existing `units` field may be
  set to the requested token/unit count.
- For `verify` and `source`, enforce units per day.
- A call is allowed only when existing usage plus requested usage stays within the
  positive configured limit.
- `check_spend()` must not write the ledger. Recording is a separate explicit action.
- `record_usage()` writes exactly one ledger row for one completed call/batch.
- A cap hit does not consume or record usage.
- Store or database failure raises explicitly; callers must fail closed and must not
  run the paid call.

## Postgres ledger store

Add `app/services/budget/spend_caps.py` with a small `SqlSpendLedgerStore`:

```python
class SqlSpendLedgerStore:
    def __init__(self, session):
        self.session = session

    async def sum_units(...): ...
    async def sum_usd(...): ...
    async def add_usage(...): ...
```

The store should query `SpendLedger` and aggregate in SQL. It must use the existing
model and UTC `day` column. It should not create a `SpendLedger` row for a denied call.

For a later provider call, the intended usage pattern is:

```python
check = await check_spend(store, "llm", limits, units, estimated_usd)
if not check.allowed:
    pause_step()
else:
    result = await paid_provider_call()
    await record_usage(store, "llm", units, estimated_usd)
```

Module 8 does not implement `paid_provider_call()`.

## Atomic cap check

The SQL store must be safe under concurrent workers. Add an atomic database
operation if the call can reserve usage before running the paid provider:

- Prefer a database transaction with a row lock or an aggregate plus `FOR UPDATE`
  on an existing per-day kind row.
- If no aggregation row exists, insert or update atomically.
- Do not add a new table unless it is genuinely required.
- At minimum, document and test the concurrency assumption used.

Because the default API separates check and record, a split check/record can race.
The implementation must therefore add an atomic reserve method or a SQL-backed
transaction helper, not claim concurrency safety from the basic summary functions.

A minimal safe shape is:

```python
async def reserve_usage(
    store,
    kind,
    day,
    units,
    est_usd,
    limits,
) -> SpendCheck:
    ...
```

For Module 8, providers may use `check_spend` plus `record_usage` only if the
implementation explicitly marks that as not reserving and no concurrent paid calls
will use it. The recommended implementation is a real atomic reserve, with a later
provider call and ledger record only after successful completion.

Do not overextend into Redis reservations. Postgres is the source of truth.

## Spend summaries

`spend_summary(store, kind, day)` should return:

```json
{
  "kind": "llm",
  "today_units": 120,
  "today_est_usd": 1.25,
  "month_units": 340,
  "month_est_usd": 8.75
}
```

The summary implementation should:

- Use UTC calendar boundaries.
- Aggregate `units` and `est_usd` with the store.
- Never expose database rows or secrets.
- Return zero values when no ledger rows exist.

Month-to-date means the first day of the supplied month's UTC calendar through
the supplied day, inclusive.

## Tests

Create focused `tests/test_spend_caps.py` coverage:

### In-memory/fake store tests

- No limit configured: every kind is denied.
- Exact boundary: usage exactly equal to a limit is allowed only for a request that
  remains within the limit.
- One unit or USD over the limit is denied.
- LLM cap is based on estimated USD, with units stored independently.
- Verification and source caps are based on units.
- Unknown kind raises `ValueError`.
- Negative units/USD raise `ValueError`.
- Non-finite limits/USD raise `ValueError`.
- Cap hit does not add a ledger row.
- Successful usage adds one ledger row.
- Concurrent fake-store reservations never exceed a limit.
- UTC day and month summaries exclude other days/months.
- Store failure is surfaced and no paid call is started.
- Compliance actions are not coupled to spend; no spend function calls
  `transition()`, suppression, or bounce handling.

### SQL store tests

Use a fake async SQL session or existing test seams rather than a real network:

- Aggregates units and USD for only the requested kind/date range.
- Inserts usage with `day`, `kind`, `units`, and `est_usd`.
- Atomic reserve prevents two concurrent callers from exceeding a limit.

Run a real-Postgres integration test only if `TEST_DATABASE_URL` is explicitly
configured. It must use the existing migration and test database, and it must not
touch a real provider or send email.

## Acceptance checklist

- [ ] `MAX_LLM_USD_PER_DAY`, `MAX_VERIFICATIONS_PER_DAY`, and
      `MAX_SOURCE_CREDITS_PER_DAY` are documented and loaded by `Settings`.
- [ ] No cap can be silently bypassed by a zero or invalid limit.
- [ ] `llm`, `verify`, and `source` kinds are the only supported kinds.
- [ ] Cap checks do not record usage.
- [ ] Successful usage creates a ledger row.
- [ ] A cap hit pauses the relevant step and emits no send/state/compliance side effect.
- [ ] Concurrent reservations cannot exceed a configured limit.
- [ ] Today's and month-to-date summaries are UTC and inclusive.
- [ ] No secrets or provider billing values are read into logs.
- [ ] Tests cover boundary, invalid input, store failure, concurrency, and summaries.
- [ ] `pytest` passes with the implementation.
- [ ] `PROGRESS.md` marks Module 8 done and points to Module 9.
