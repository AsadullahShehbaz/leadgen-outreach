# Module 5 Plan - send_due + FakeMailProvider

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 3, 11-13, 16, and 22
(module 5).
Acceptance test from the design: **two workers never double-send**.

## Goal

Implement the sending engine that safely turns queued enrollments into sent `Message`
rows.

1. Add a real Redis connection helper and the global sending kill switch.
2. Add the `MailProvider` interface and a no-network `FakeMailProvider`.
3. Implement `send_due()` as an idempotent ARQ job.
4. Build a complete outbound message with:
   - mandatory sender footer,
   - opt-out link,
   - `List-Unsubscribe`,
   - `In-Reply-To` and `References` for follow-ups,
   - no open-tracking pixel.
5. Test double-send, suppression, license blocking, send windows, Redis caps,
   transient failure, sticky mailboxes, and follow-up sequencing.

## Out of scope

- SMTP/IMAP production implementations.
- Inbox polling, bounce parsing, reply classification, and auto-replies.
- LangGraph personalization and lead sourcing.
- Spending-ledger implementation.
- License token creation or Ed25519 verification. Module 11 supplies the real
  license implementation.
- `/send` HTTP endpoints.
- Per-hour pacing and jitter, which are required but depend on later design details;
  this module reserves the mailbox pacing seam.

## Decisions

| Question | Decision |
|---|---|
| Job name | `send_due(ctx)` in `app/workers/jobs.py` or a small module under `app/workers/`. |
| Queue trigger | ARQ cron every minute. Add worker settings only as needed by this module. |
| Row locking | Select 50 due active enrollments with `SELECT ... FOR UPDATE SKIP LOCKED`. |
| Mailbox lock | Sticky mailbox: use `Enrollment.mailbox_id` for follow-ups; choose an active mailbox for the first send. |
| Kill switch | Read `SENDING_ENABLED` from Redis/config; default fail closed to disabled. |
| Suppression failure | Fail closed: block the enrollment and do not release/consume a send slot. |
| License failure | Block new sends only; suppressions and state changes remain independent. |
| Window failure | Leave the enrollment active and set `next_send_at` to the next window opening. |
| Transient send failure | Release the acquired Redis slot once and apply bounded backoff. |
| Permanent send failure | Record no `Message`, block or release according to provider result; do not invent a retry rule beyond a clear provider exception type. |
| Sequence advance | `queued -> step1_sent`, `step1_sent -> step2_sent`, `step2_sent -> step3_sent`, and `step3_sent -> completed` through `transition()`. |
| Follow-up timing | Use the campaign's next `SequenceStep.delay_days` and set `next_send_at` in UTC. |
| Idempotency | A `Message` record and provider message ID are the send receipt; duplicate jobs must not create a second provider send. |
| Test provider | `FakeMailProvider` stores sent messages in memory and can fail by exception mode. |

## Deliverables

```text
backend/
  app/core/
    redis.py                 # NEW: RedisLike, get_redis
  app/services/
    mail/
      base.py                # NEW: OutboundMessage, MailProvider, TransientSendError
      fake.py                # NEW: FakeMailProvider
    sequencing/
      send_due.py            # NEW: send_due orchestration and small pure helpers
  app/workers/
    arq_settings.py          # NEW or update: WorkerSettings and send_due cron
    jobs.py                  # NEW or update: send_due job
  tests/
    test_send_due.py         # NEW
    test_mail_provider.py    # NEW
docs/plan/
  module-05-send-due.md      # this plan
PROGRESS.md
README.md
```

No database migration is required unless implementation reveals a missing field that
the design already requires.

## Interfaces

### Redis

```python
class RedisLike(Protocol):
    async def incr(self, key: str) -> int: ...
    async def decr(self, key: str) -> int: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    async def get(self, key: str) -> str | bytes | None: ...
```

`get_redis()` creates one Redis client for the application. Use `REDIS_URL` from
settings. Never pass secrets or email bodies to Redis.

### Mail provider

```python
class MailProvider(Protocol):
    async def send(self, mailbox: Mailbox, message: OutboundMessage) -> str:
        ...
```

`OutboundMessage` contains:

- `from_address`
- `to_address`
- `subject`
- `body`
- `headers` (for `List-Unsubscribe`, `In-Reply-To`, and `References`)

`TransientSendError` is the only provider exception that releases the Redis cap and
backs off.

`FakeMailProvider.send()`:

- returns a deterministic test `message_id`,
- records each call in memory,
- may be configured to raise `TransientSendError`,
- never performs DNS, SMTP, or network I/O.

## Send order

The implementation must preserve this exact order:

1. Kill switch.
2. Lock due active enrollment rows with `SKIP LOCKED`.
3. Re-check suppression.
4. Re-check license allowance for sending.
5. Pick mailbox.
6. Re-check send window.
7. Acquire one Redis mailbox/day cap slot.
8. Build the message.
9. Send through `MailProvider`.
10. Record `Message`.
11. Advance enrollment through `transition()`.
12. Commit once for each row batch.

License problems may block only sourcing and new sends. They must never block
suppression or unsubscribe handling.

## Message building

`build_message()` is a small pure function that receives all required values explicitly:

- enrollment,
- mailbox,
- lead and lead email,
- workspace sender identity/postal address,
- subject and body supplied by the personalization stage,
- opt-out URL.

It must:

- call `build_footer()` rather than duplicating footer logic,
- append the mandatory opt-out footer once,
- include a `List-Unsubscribe` header using the opt-out URL,
- set `In-Reply-To` to the previous outbound `Message.message_id` for follow-ups,
- set `References` to the previous thread IDs,
- include no image, tracking pixel, or beacon.

No email body or full message is written to logs.

## Sending helpers

Keep `send_due.py` simple and beginner-friendly:

```python
async def is_suppressed_for_enrollment(db, enrollment) -> bool:
    ...

async def pick_mailbox(db, enrollment) -> Mailbox | None:
    ...

def in_enrollment_send_window(workspace, now) -> bool:
    ...

def next_enrollment_send_at(workspace, now) -> datetime:
    ...

def advance_enrollment(db, enrollment, reason) -> None:
    ...

def backoff_enrollment(enrollment, now) -> datetime:
    ...
```

The database-backed `is_suppressed_for_enrollment()` and `pick_mailbox()` stay behind
small functions instead of embedding SQL into the worker loop.

## Locking and idempotency

- Use the enrollment row lock returned by `SKIP LOCKED`.
- Call `transition()` before setting provider-related data or scheduling follow-ups.
- Record exactly one outbound `Message` for one provider `message_id`.
- If `send_due()` sees an `Enrollment` twice due to concurrent workers, only the worker
  holding the locked row can advance it.
- Provider failure after a successful send but before the local commit is a crash
  window. Deduplicate by provider `Message-ID`/local `Message.message_id` when
  recovering; no second provider send is allowed after recording that ID.

## Tests

### `test_send_due.py`

- Sending is disabled and no enrollment is changed.
- Suppressed email transitions to `unsubscribed` and is never sent.
- License blocked: no send, and no state transition or suppression change.
- Invalid/paused mailbox: no send.
- Enrollment outside the send window moves `next_send_at` to `next_window`.
- Daily cap reached: no send and no state transition.
- Exactly `cap` enrollments can acquire independent slots.
- Successful sends record `Message`, call the fake provider once, and advance state.
- `queued -> step1_sent`, `step1_sent -> step2_sent`,
  `step2_sent -> step3_sent`, and `step3_sent -> completed`.
- Sticky mailbox remains on follow-ups.
- First send chooses one active workspace mailbox.
- `TransientSendError` releases the limiter slot exactly once and applies backoff.
- Permanent provider failure records no `Message`.
- Message includes footer, opt-out URL, `List-Unsubscribe`, and thread headers.
- No provider call contains a tracking pixel.
- Concurrent workers cannot send the same enrollment twice.
- Crash/replay with an existing `Message.message_id` does not send again.

### `test_mail_provider.py`

- `FakeMailProvider` sends no network and returns its configured message ID.
- Multiple fake sends are recorded independently.
- Configured transient failure raises `TransientSendError`.
- `OutboundMessage` does not expose or log credentials.

## Implementation order

1. Add `REDIS_URL`, `SENDING_ENABLED`, and send-window settings to `.env.example`.
2. Add `app/core/redis.py`.
3. Add `app/services/mail/base.py` and `fake.py`.
4. Add pure send-window, backoff, footer, and message-building helpers.
5. Add database `pick_mailbox()` and suppression lookup helpers.
6. Implement `send_due()` with the exact check order.
7. Add ARQ worker settings and cron registration.
8. Write focused tests with fake Redis, fake mail, fake license, and fake/small DB
   seams.
9. Run the focused Module 5 suite first.
10. Run the full `pytest` suite and confirm Modules 1-4 remain green.
11. Update `PROGRESS.md` and `README.md`.

## Acceptance checklist

- [x] Two concurrent workers never send the same enrollment twice.
- [x] Kill switch blocks all sends.
- [x] Suppression is rechecked immediately before send.
- [x] License failure blocks sends but never unsubscribe/suppression handling.
- [x] Mailbox is sticky across follow-ups.
- [x] Workspace send window is enforced with timezone/DST correctness.
- [x] Redis cap is never exceeded.
- [x] Transient failure releases the acquired slot exactly once.
- [x] Successful send records `Message` and advances status through `transition()`.
- [x] Replay is idempotent.
- [x] Message has a footer and opt-out headers; no open tracking is added.
- [x] Tests use only fake providers and fake Redis.
- [x] Full suite passes.
- [x] `PROGRESS.md` marks Module 5 done and points to Module 6.

## Risks to watch

- **Double-send:** Provider and database state must not be changed outside the row
  lock and state-machine rules.
- **License coupling:** Sending and compliance must use separate decisions.
- **Timezone:** Reuse `windows.py`; never silently fall back to UTC.
- **Redis failure:** Fail closed for cap or kill-switch access rather than sending
  without protection.
- **Email body logs:** Never log subject, body, provider response, or credentials.
- **Crash after provider send:** Store the provider `Message-ID` once and deduplicate
  replay by it.
