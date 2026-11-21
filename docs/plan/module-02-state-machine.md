# Module 2 Plan — Enrollment State Machine

Status: implemented in code (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Section 11 (lead lifecycle) and Section 22 (module 2).
Acceptance test from the design: **illegal transitions raise.**

## Goal

Build one small, strict gatekeeper for `Enrollment.status`. Every status change in the
system must go through `services/sequencing/state_machine.py`; no other code may assign
`Enrollment.status` directly.

An enrollment is one lead's journey through one campaign. Think of the state machine as
a strict receptionist sitting in front of that column:

- It only allows moves written in its rulebook.
- It rejects anything else immediately (for example, a `replied` lead can never jump to `step2_sent`).
- It writes a diary entry (`events` row) for every accepted move.

This is boring code that prevents catastrophic bugs: emailing someone who said stop,
emailing a bounced address, or sending step 3 to someone who already replied.

Out of scope: `step_no` advancement, `next_send_at` scheduling, send windows, the Redis
limiter, suppression checks, `send_due`, inbox polling, HTTP endpoints, workers.

No schema change, so no Alembic migration. This module is pure logic plus one `Event` insert.

## Lifecycle

13 statuses in total:

- **Progress (8):** `new`, `scored`, `verified`, `drafted`, `queued`, `step1_sent`,
  `step2_sent`, `step3_sent`
- **Endings (5):** `completed`, `rejected`, `replied`, `bounced`, `unsubscribed`

```text
new -> scored -> verified -> drafted -> queued -> step1_sent -> step2_sent -> step3_sent -> completed

rejected may follow new, scored, verified or drafted.
replied, bounced and unsubscribed may follow queued, step1_sent, step2_sent or step3_sent.
```

## Locked decisions

- **Statuses stay plain strings.** No Postgres enums, no Python Enum; the rulebook validates them.
- **Exact design table.** Copy `ALLOWED` from Section 11 unchanged; do not invent extra moves.
- **Terminal means no way out.** `TERMINAL = EXIT | {"completed", "rejected"}` where
  `EXIT = {"replied", "bounced", "unsubscribed"}`.
- **`transition()` does not commit.** The caller owns the transaction and commits once.
  This keeps multi-step jobs atomic (for example, `send_due` later).
- **Validate before mutating.** On an illegal move, raise before changing status or adding an event.
- **One event per accepted move.** `type = "status:<new_status>"`,
  `payload = {"reason": reason, **(payload or {})}` exactly as in the design.
- **Unknown current status raises.** `ALLOWED.get(status, set())` means a typo or legacy
  status cannot silently pass.

Sets used by this and later modules:

```python
ACTIVE = {"queued", "step1_sent", "step2_sent", "step3_sent"}
EXIT = {"replied", "bounced", "unsubscribed"}
TERMINAL = EXIT | {"completed", "rejected"}
```

## Rulebook (from design Section 11)

| From | Allowed to |
|---|---|
| `new` | `scored`, `rejected` |
| `scored` | `verified`, `rejected` |
| `verified` | `drafted`, `rejected` |
| `drafted` | `queued`, `rejected` |
| `queued` | `step1_sent`, `replied`, `bounced`, `unsubscribed` |
| `step1_sent` | `step2_sent`, `completed`, `replied`, `bounced`, `unsubscribed` |
| `step2_sent` | `step3_sent`, `completed`, `replied`, `bounced`, `unsubscribed` |
| `step3_sent` | `completed`, `replied`, `bounced`, `unsubscribed` |

That is 26 allowed moves and 143 illegal moves across all 13 x 13 pairs.

## Deliverables

```text
backend/
  app/services/sequencing/
    __init__.py                 # empty package marker
    state_machine.py            # ACTIVE, EXIT, TERMINAL, ALLOWED,
                                # IllegalTransition, transition()
  tests/
    test_state_machine.py       # every allowed and illegal move; no database needed
docs/plan/
  module-02-state-machine.md    # this plan
```

Open choice: also write `docs/tutorials/module2.md` in the style of Module 1 (optional).

## How `transition()` works

```python
async def transition(db, enrollment, new_status, reason, payload=None):
```

1. Read the allowed moves for `enrollment.status`. Unknown or ending status means no moves.
2. If `new_status` is not allowed, raise `IllegalTransition(current, new)` **before changing anything**.
3. Set `enrollment.status = new_status`.
4. If the new status is in `TERMINAL`, set `enrollment.next_send_at = None`.
5. Add one `Event` row:
   - `enrollment_id=enrollment.id`
   - `type=f"status:{new_status}"`
   - `payload={"reason": reason, **(payload or {})}`
6. Return nothing. Do not commit or flush; the caller commits.

`IllegalTransition` lives in the same file and carries both statuses plus a readable
message such as `cannot move enrollment from 'replied' to 'step2_sent'`.

## Implementation order

1. Create `app/services/sequencing/__init__.py` and `state_machine.py` with the sets,
   the exception and `transition()`.
2. Write `tests/test_state_machine.py` using a tiny fake session.
3. Run from `backend/`: `venv\Scripts\python.exe -m pytest -q`.
4. Review that no other module assigns `Enrollment.status`.
5. Update `PROGRESS.md` (Module 2 done, next Module 3) and the README status line.
6. Optional: write `docs/tutorials/module2.md`.

No `backend/.env`, Supabase, Redis or network access is needed, so this module can be
built even while the Module 1 live migration is still pending.

## Tests

A tiny fake session keeps the tests database-free:

```python
class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)
```

Test cases:

- All 26 allowed moves succeed and set the expected status.
- All 143 illegal moves raise `IllegalTransition`, leave the status unchanged and add no event.
- An unknown current status (for example `"banana"`) raises instead of silently passing.
- Terminal moves clear `next_send_at`; normal moves keep it.
- The event has the right type and includes `reason` plus any extra payload.
- Rulebook sanity: every key and target is a known status; `ACTIVE` and `TERMINAL` do not
  overlap; every status is either a key in `ALLOWED` or terminal.

## Acceptance checklist

- [x] Every allowed transition succeeds.
- [x] Every illegal transition raises.
- [x] Illegal moves do not change status and do not write an event.
- [x] Terminal moves clear `next_send_at`; non-terminal moves leave it alone.
- [x] `pytest` passes with the existing tests still green.
- [x] Only `services/sequencing/state_machine.py` writes `Enrollment.status` (review).
- [x] `PROGRESS.md` updated and Module 2 ticked in the build-order table.

## Implementation notes (2026-11-21)

- Implemented exactly as planned. The `Event` payload follows the design literally:
  `{"reason": reason, **payload}` with no extra `from` field.
- Tests: 26 allowed moves, 143 illegal moves, unknown current status, reason plus extra
  payload, missing payload, and rulebook consistency. Full suite: 182 passed, 1 skipped
  (the existing migration integration test).
- No database, Redis, network or `backend/.env` is needed for this module.
- Optional `docs/tutorials/module2.md` was not written.

## Risks to watch

- **Sneaky direct writes:** future code may be tempted to set `enrollment.status = ...`
  directly. Always call `transition()`; catch this in review.
- **Accidental commit:** if `transition()` commits, later steps in the same job can be
  half-saved. Keep transaction ownership with the caller.
- **Rulebook drift:** if a status is added later, update both `ALLOWED` and the terminal
  sets; the sanity tests catch a forgotten status.
- **String typos:** an unknown current status raises, which is safer than guessing, but
  error messages should show the exact string to make debugging easy.
