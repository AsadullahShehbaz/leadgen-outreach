# Module 3 Plan — Redis Daily Cap Limiter + Send Windows

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 13 (jobs and the send
engine) and 22 (module 3).
Acceptance test from the design: **cap never exceeded**.

## Goal

Build the two pure-logic safety pieces that `send_due` will call in Module 5:

1. **Daily cap limiter** — atomically reserve one send slot per mailbox per local day in Redis.
2. **Send windows** — decide whether "now" is inside the client's business hours, and
   compute the next opening.

No database, no Supabase, no live Redis required for the test suite. No migration.

Out of scope: `send_due`, mailbox selection, per-hour pacing, jitter, suppression, license,
message building, kill switch, HTTP endpoints, ARQ wiring.

## Decisions (confirmed)

| Question | Decision |
|---|---|
| Window hours/days | Default Mon–Fri, **09:00–17:00** workspace local time, env-configurable |
| Cap reset clock | **Workspace-local date** (uses `workspaces.timezone`) |
| Pacing + jitter | Deferred to Module 5 (`send_due`) |
| Timezone data | Add **`tzdata`** to `requirements.txt` (Windows/Docker need it for `ZoneInfo`) |

## Deliverables

```text
backend/
  requirements.txt                         # + tzdata
  app/core/config.py                       # window settings + TEST_REDIS_URL
  .env.example                             # document new settings
  app/services/sequencing/
    windows.py                             # NEW: SendWindow, in_send_window, next_window, workspace_day
    limiter.py                             # NEW: RedisLike, cap_key, try_acquire, release
  tests/
    test_windows.py                        # NEW
    test_limiter.py                        # NEW
docs/plan/
  module-03-limiter-windows.md             # this plan
PROGRESS.md                                # Module 3 done, next Module 4
README.md                                  # update status line
```

Optional: `docs/tutorials/module3.md` in the Module 1 style.

## Send windows (`windows.py`)

```python
@dataclass(frozen=True)
class SendWindow:
    start_hour: int = 9
    end_hour: int = 17
    weekdays: frozenset[int] = frozenset({1, 2, 3, 4, 5})  # ISO: 1=Mon .. 7=Sun

def window_from_settings() -> SendWindow: ...
def in_send_window(now, tz_name, window) -> bool: ...
def next_window(now, tz_name, window) -> datetime: ...   # returns UTC
def workspace_day(now, tz_name) -> date: ...
```

Semantics:

- `now` must be timezone-aware; naive input raises `ValueError`.
- Timezone comes from `Workspace.timezone`; invalid names raise `ZoneInfoNotFoundError`
  (fail loudly, never silently send in UTC).
- Window is local wall-clock time: `start_hour <= local.hour < end_hour`; weekdays use
  `isoweekday()`.
- DST is handled by `ZoneInfo`; no custom offset math.
- `next_window()` returns the next window opening at or after `now`, converted back to UTC.
  Callers only call it when `in_send_window()` is false.
- `workspace_day()` returns the local calendar date used for the Redis cap key.
- `SendWindow` validates `0 <= start < end <= 23` and non-empty weekdays 1–7.
- `window_from_settings()` parses `SEND_WINDOW_DAYS` (comma-separated ISO weekday
  numbers); malformed input raises a clear `ValueError`.

## Limiter (`limiter.py`)

```python
CAP_TTL_SECONDS = 60 * 60 * 30   # 30 hours, per design

def cap_key(mailbox_id, day: date) -> str:
    return f"cap:{mailbox_id}:{day:%Y%m%d}"

async def try_acquire(redis, mailbox_id, cap: int, day: date) -> bool: ...
async def release(redis, mailbox_id, day: date) -> None: ...
```

`try_acquire()` exactly mirrors Section 13:

1. `cap <= 0` → return `False` without touching Redis.
2. `n = await redis.incr(key)`.
3. If `n == 1`, set `expire(key, 30h)`.
4. If `n > cap`, `decr(key)` and return `False`.
5. Otherwise return `True`.

`release()` decrements the counter; used later when a send fails transiently. The caller
must release exactly once per acquired slot.

Redis dependency is a tiny `RedisLike` Protocol (`incr`, `decr`, `expire`) so production
passes a real `redis.asyncio.Redis` and tests pass a fake. No Redis client factory yet;
Module 5 adds `REDIS_URL` and `core/redis.py`.

## Config additions

In `Settings` and `.env.example`:

```text
SEND_WINDOW_START_HOUR=9
SEND_WINDOW_END_HOUR=17
SEND_WINDOW_DAYS=1,2,3,4,5   # ISO weekdays, 1=Monday .. 7=Sunday

# Optional: test-only Redis for the limiter integration test.
TEST_REDIS_URL=redis://localhost:6379/15
```

## Tests

`tests/test_windows.py` (no DB, no network, fixed `now` values):

- Before start, exact start, mid-window, last minute, exact end, weekend.
- Same UTC instant interpreted in UTC vs `Asia/Karachi` proves the timezone conversion.
- `next_window()` before today's start → today; after end on Friday → Monday; during
  weekend → Monday; exact opening → now.
- DST test in `America/New_York`: Friday after close → Monday 09:00 EDT equals 13:00 UTC.
- `workspace_day()` differs from UTC date around local midnight.
- Naive datetime and unknown timezone raise.
- Invalid window config and malformed `SEND_WINDOW_DAYS` raise.

`tests/test_limiter.py` with a tiny `FakeRedis` (dict + `asyncio.Lock` to mimic atomic
commands):

- First acquire creates `cap:{mailbox}:{YYYYMMDD}` and sets 30h TTL.
- Exactly `cap` acquisitions succeed; `cap + 1` fails and counter stays at `cap`.
- Different mailboxes and different days have independent caps.
- `cap <= 0` never creates a key.
- `release()` frees a slot for a later acquire.
- **Concurrency:** 200 concurrent `asyncio.gather` acquires with cap 10 → exactly 10
  `True`, counter 10.
- **Concurrency:** three mailboxes × 50 tasks each → each mailbox capped independently.
- Optional `@pytest.mark.integration` test against `TEST_REDIS_URL` (skipped when unset)
  to prove real-Redis atomicity; uses a random mailbox UUID and deletes only its own key.

## Implementation order

1. Add `tzdata` to `requirements.txt`; install into `venv` (`pip install tzdata`).
2. Add config fields + `.env.example` entries.
3. Write `windows.py`; write `test_windows.py`.
4. Write `limiter.py`; write `test_limiter.py` (fake + optional integration).
5. Run `venv\Scripts\python.exe -m pytest -q` from `backend/` — existing 182 tests must
   stay green.
6. Update `PROGRESS.md` and `README.md`.
7. Optional: `docs/tutorials/module3.md`.

## Acceptance checklist

- [x] Daily cap is never exceeded under 200 concurrent acquires (fake and, when
      configured, real Redis).
- [x] `cap <= 0` can never acquire a slot.
- [x] Cap keys expire after 30 hours and include mailbox + workspace-local date.
- [x] Send windows are correct across timezones, boundaries, weekends, and DST.
- [x] `next_window()` always returns a UTC datetime inside the next allowed window.
- [x] Invalid window config and invalid timezones fail loudly.
- [x] Full test suite passes with Module 1 and 2 tests unchanged.
- [x] `PROGRESS.md` ticked and "Next step" points at Module 4.

## Risks to watch

- **INCR + EXPIRE are two commands**, matching the design. A crash between them could
  leave a key without TTL; the 30h key includes the date, so impact is limited to one day.
  Note this in code comments.
- **Double `release()`** would under-count and could allow extra sends. Keep the "one
  release per acquire" rule visible in the function docstring and enforce it in Module 5.
- **Invalid workspace timezone** must make `send_due` skip, not send in UTC. Module 3
  raises; Module 5 must catch and log.
- **Env typo in `SEND_WINDOW_DAYS`** fails at startup/first use rather than silently
  using defaults.
