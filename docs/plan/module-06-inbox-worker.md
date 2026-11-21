# Module 6 Plan - Inbox Worker

Status: not started.
Design reference: `docs/leadgen-system-design-v2.md`, Sections 3, 11-13, 16,
and 22 (module 6).
Acceptance test from the design: **a reply stops the sequence and a hard bounce
suppresses the prospect**.

## Goal

Implement the inbound mail worker that safely processes bounces and replies:

1. Add inbound mail types to the existing `MailProvider` interface.
2. Implement a bounce parser for DSN 4.x.x and 5.x.x responses.
3. Match each inbound message to an outbound `Message` through
   `In-Reply-To` or `References`.
4. Classify replies behind a separate fakeable interface.
5. Implement the `poll_inbox` ARQ cron job.
6. Stop sequences, suppress opt-outs and bounces, and update mailbox health
   without depending on license validity.

## Out of scope

- SMTP/IMAP production providers.
- Automatic replies or drafted email sends to prospects.
- Open-tracking pixels.
- `/inbox` HTTP endpoints.
- Real LLM reply classification. Module 6 uses a fake classifier and keeps a
  small interface for Module 10 or a later implementation.
- Telegram, email, or webhook notifications.
- Warm-up ramping and spend optimization.
- Modifying sending behavior through license checks.

## Decisions

| Question | Decision |
|---|---|
| Bounce handling | Parse only DSN status codes in `4.x.x` and `5.x.x` format. |
| Soft bounce limit | Retry later. Stop and treat as hard after 3 failures. |
| Hard bounce | Mark the lead email invalid, add SHA-256 suppression, and transition to `bounced`. |
| Reply handling | Match thread headers first, then stop a matched enrollment. |
| Unsubscribe reply | Suppress the prospect immediately and permanently. |
| Normal reply | Transition once to `replied`; do not send an auto-response. |
| Reply classes | `interested`, `question`, `not_now`, `not_interested`, `unsubscribe`, `out_of_office`, `referral`, `auto_reply`, `other`. |
| Classifier interface | Define a small `ReplyClassifier` protocol and `FakeReplyClassifier`. |
| Bounce parser | Pure, beginner-friendly parsing functions with no network or database access. |
| Mail provider | Extend `MailProvider` with `fetch_new`; use `FakeMailProvider` in tests. |
| Idempotency | One inbound `Message.message_id` must produce only one state change and one suppression update. |
| License | Inbound bounce, unsubscribe, suppression, and reply work never checks license state. |
| Mailbox health | Hard bounces and complaints increase health penalties; pause above the design thresholds. |

## Deliverables

```text
backend/
  app/services/
    mail/
      base.py                # update: InboundMessage and fetch_new interface
      fake.py                # update: fake inbound records
      bounce_parser.py       # NEW: pure 4.x.x / 5.x.x parser
    agents/
      reply_classifier.py    # NEW: ReplyClassifier protocol and fake implementation
    sequencing/
      inbox_worker.py        # NEW: poll and process orchestration
  app/workers/
    arq_settings.py          # update: inbox cron
    jobs.py                  # update: poll_inbox job
  tests/
    test_bounce_parser.py    # NEW
    test_inbox_worker.py     # NEW
docs/plan/
  module-06-inbox-worker.md # this plan
PROGRESS.md
README.md
```

No migration is required unless implementation reveals that the existing
`Message` and `Mailbox` fields cannot represent a design-required state.

## Interfaces

### MailProvider

Keep sending and inbox operations behind the existing provider protocol:

```python
@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    in_reply_to: str | None
    references: tuple[str, ...]
    from_address: str
    to_address: str
    subject: str
    body: str
    headers: dict[str, str] = field(default_factory=dict)
```

```python
class MailProvider(Protocol):
    async def send(
        self,
        mailbox: Mailbox,
        message: OutboundMessage,
    ) -> str: ...

    async def fetch_new(
        self,
        mailbox: Mailbox,
        since_uid: int,
    ) -> list[InboundMessage]: ...
```

The UID cursor can remain provider-specific. Module 6 should store no provider
secrets and log no subject or body.

### Bounce parser

The parser should accept raw DSN text and return a simple result:

```python
@dataclass(frozen=True)
class BounceResult:
    kind: Literal["hard", "soft", "unknown"]
    status_code: str | None
```

Parsing rules:

- `5.x.x` returns `hard`.
- `4.x.x` returns `soft`.
- Missing or malformed DSN status returns `unknown`.
- Never infer a hard bounce from ordinary reply text.

### Reply classifier

```python
class ReplyClassifier(Protocol):
    async def classify(
        self,
        message: InboundMessage,
    ) -> str: ...
```

`FakeReplyClassifier` accepts a configured class or defaults to `other`. Tests
must use the fake and never call an external LLM or network.

## Worker behavior

`poll_inbox(ctx)` should:

1. Read active mailboxes and process each mailbox independently.
2. Fetch new inbound messages through `ctx["mail"].fetch_new(...)`.
3. Parse bounce/complaint signals before reply matching.
4. Match inbound thread data to the most recent outbound `Message`.
5. Add exactly one inbound `Message` record for idempotency.
6. Apply bounce or reply state changes with `transition()`.
7. Commit mailbox and enrollment changes for the mailbox batch.
8. Never auto-reply to a prospect.

License state is not read by this worker.

## Bounce handling

For a hard bounce:

- Set `LeadEmail.verify_status = "invalid"`.
- Suppress the email through `add_suppression(..., "bounced")`.
- Transition the enrollment to `bounced`.
- Record an inbound `Message` and event.
- Apply a mailbox health penalty and pause the mailbox if the rolling hard
  bounce threshold exceeds 2-3%.

For a soft bounce:

- Record the inbound message.
- Increment a bounded soft-bounce retry count available to the worker.
- Retry later.
- After 2-3 failed soft-bounce attempts, treat the address as hard and apply the
  hard-bounce flow.

If a bounce cannot be matched to an enrollment, it must still be recorded without
email or subject body logging and never trigger an outbound send.

## Reply handling

For one reply:

- Match `In-Reply-To` exactly to an outbound `message_id`.
- If no exact match exists, find the first outbound `Message.message_id` present
  in `References`.
- If still unmatched, do not change any enrollment.
- If matched, classify the reply.
- If class is `unsubscribe`, suppress and transition to `unsubscribed`.
- If class is `auto_reply`, do not stop the sequence.
- For every other reply class except `auto_reply`, transition to `replied`.
- Store the classifier result in the inbound `Message` or an `Event`; do not
  invent a separate database table.
- Never send an automatic reply.

## Spam complaints

If the provider exposes a complaint signal in `InboundMessage.headers`, treat
it as a suppression event:

- Suppress the prospect email.
- Transition the matched enrollment to `unsubscribed`.
- Apply a mailbox complaint penalty.
- Pause the mailbox if complaint rate approaches 0.3%.

No provider implementation or real mailbox is required in this module.

## Tests

### `test_bounce_parser.py`

- Hard status `5.1.1` is hard.
- Soft status `4.2.0` is soft.
- Other status values are unknown.
- Missing or malformed status is unknown.
- Ordinary reply text never parses as a bounce.
- Parsing with mixed casing and whitespace remains stable.

### `test_inbox_worker.py`

- `In-Reply-To` finds the enrollment and stops it once.
- `References` finds the thread fallback.
- An unmatched reply does not stop any enrollment.
- `unsubscribe` reply suppresses and transitions to `unsubscribed`.
- `interested`, `question`, `not_now`, `not_interested`, and `other` stop to
  `replied`.
- `auto_reply` does not stop the sequence.
- Hard bounce suppresses and transitions to `bounced`.
- Soft bounce does not suppress and does not end the enrollment.
- Third soft bounce becomes a hard bounce.
- Replay of the same inbound `message_id` has no duplicate effect.
- Replay under an expired or missing license still processes compliance.
- Fake provider fetch never performs network I/O.
- No tracking pixel or automatic reply is created.
- High hard-bounce or complaint health penalty pauses the mailbox.

## Implementation order

1. Add `InboundMessage`, `ReplyClassification` or simple string result types,
   and `fetch_new()` to `app/services/mail/base.py`.
2. Extend `FakeMailProvider` with deterministic inbound messages.
3. Add `app/services/mail/bounce_parser.py`.
4. Add `app/services/agents/reply_classifier.py` with protocol and fake.
5. Add mailbox and thread matching helpers in `app/services/sequencing/inbox_worker.py`.
6. Implement replay-safe inbound `Message` recording.
7. Implement hard bounce, soft bounce, and reply handling.
8. Add mailbox health and threshold helpers.
9. Register `poll_inbox` in `jobs.py` and ARQ cron settings.
10. Write focused bounce and inbox tests.
11. Run the focused Module 6 suite.
12. Run the full `pytest` suite and confirm Modules 1-5 remain green.
13. Update `PROGRESS.md` and `README.md`.

## Acceptance checklist

- [x] Reply matching with `In-Reply-To` stops the sequence.
- [x] Reply matching with `References` stops the sequence.
- [x] Unsubscribe reply suppresses permanently.
- [x] Hard bounce suppresses and sets the enrollment to `bounced`.
- [x] Soft bounce retries before hard-bounce handling.
- [x] Replayed inbound messages produce no duplicate state changes.
- [x] License failure never blocks bounce or reply handling.
- [x] Spam complaints suppress and affect mailbox health.
- [x] Mailbox pauses at the design threshold.
- [x] Reply classification uses only fake providers in tests.
- [x] No auto-reply or open-tracking behavior exists.
- [x] Tests use only fake mail and fake classifier implementations.
- [x] Full suite passes.
- [x] `PROGRESS.md` marks Module 6 done and points to Module 7.

## Risks to watch

- **False bounce parsing:** Use exact DSN status codes, not broad text matches.
- **Wrong thread match:** Use `In-Reply-To` first, then exact `References`
  matching.
- **Duplicate processing:** Check `Message.message_id` before state changes.
- **License coupling:** Never import or call license code from the inbox path.
- **Email body logs:** Never log subject, body, DSN content, or credentials.
- **Auto-reply:** Processing replies must stop or classify; it must not send.
- **Terminal transitions:** Call `transition()` for every status change and let
  it create the event and clear `next_send_at`.
- **Malformed provider data:** Unknown DSN data and missing thread IDs must fail
  safely by recording or ignoring, never guessing.
