# Module 11 Plan - Offline License + Soft Enforcement

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 8, 13, 20-22
(module 11).
Acceptance test from the design: **expired license blocks sourcing and new sends,
but never unsubscribes or bounce handling**.

## Goal

Implement a small, offline license gate:

1. Verify an Ed25519-signed license token with the public key embedded in the app.
2. Parse and validate customer, plan, mailbox, lead, feature, and expiry claims.
3. Cache verification results in the existing `LicenseState` table.
4. Add a daily license validation job.
5. Replace placeholder send gating with the real verified-license check.
6. Block sourcing and campaign creation when the license is missing or expired.
7. Keep unsubscribe, suppression, bounce, reply, and authentication behavior
   working regardless of license state.

## Out of scope

- React license and system screens; Module 13 owns dashboard UI.
- Packaging and private-registry image distribution; Module 12 owns deployment.
- Live billing, invoices, payment collection, or vendor account checks.
- Hardware locking, code obfuscation, or a shared server license service.
- Automatic phone-home telemetry or license renewal requests.
- State-machine changes. A license block does not transition enrollments.
- Send, inbox, and compliance provider implementations; those are Modules 5-6.
- Spend enforcement changes; Module 8 already owns paid-step limits.
- New license tables or migrations; use the existing `license_state` model.

## Decisions

| Question | Decision |
|---|---|
| Signature | Ed25519 with a compact JWS-shaped token: `base64url(header).base64url(payload).base64url(signature)`. |
| JWS algorithm | The protected header must contain `"alg": "EdDSA"` and no extra critical header fields. |
| Claims | Require `customer`, `plan`, `max_mailboxes`, `max_leads_per_month`, `expires_at`, and `features`. |
| Public key | Read a PEM public key from `LICENSE_PUBLIC_KEY_PEM`, with no private key anywhere in the app or repository. |
| Missing key | Verification fails closed. Do not permit a development-only unsigned bypass. |
| Development/test key | Tests use a generated in-memory Ed25519 key pair and fake/explicit now values. |
| Expiry format | `expires_at` is an RFC 3339 UTC timestamp. Reject unknown timezone offsets and timestamps that cannot be normalized to UTC. |
| Invalid token | Reject it explicitly; do not store it or mark it valid. |
| Grace period | The existing 14-day grace period starts at `expires_at`. During grace, existing sends and sourced operations may continue as configured; after grace, block. |
| Missing license | No grace is available. Sourcing and new sends are blocked immediately. |
| Compliance paths | License checks are never called from unsubscribe, suppression, bounce, or inbox handling. |
| Source limit | `max_leads_per_month` is checked before each source batch and measured from UTC month-to-date stored leads. |
| Mailbox limit | New mailbox setup is blocked when the active license limit is reached. |
| Features | Only explicitly named feature strings enable their matching behavior. Unknown features are accepted as data but ignored. |
| State cache | `valid_until` and `last_checked_at` reflect the most recent successful signature validation. |
| Time source | Every public function accepts an optional UTC `now` argument for deterministic tests. |
| Logs/support | Log status, customer ID, expiry, and reason only. Never log the full token or public key. |

## Deliverables

```text
backend/
  app/core/
    config.py                # update: LICENSE_PUBLIC_KEY_PEM
  app/services/
    license/
      __init__.py            # NEW package
      license.py             # NEW: Ed25519 verification and enforcement helpers
  app/routers/
    setup.py                 # UPDATE: verify license before storing
    system.py                # UPDATE or NEW: authenticated license status
  app/workers/
    jobs.py                  # UPDATE: license_check ARQ job
  tests/
    test_license.py          # NEW
docs/plan/
  module-11-license.md
PROGRESS.md
README.md
```

No database migration is required. The existing `LicenseState.token`,
`LicenseState.valid_until`, and `LicenseState.last_checked_at` fields are
sufficient. Keep raw tokens encrypted or protected at rest if the deployment
implementation permits; do not expose a license token in API responses.

## Token format

Use compact JWS:

```text
base64url(header).base64url(payload).base64url(signature)
```

Example payload shape:

```json
{
  "customer": "customer-id",
  "plan": "starter",
  "max_mailboxes": 5,
  "max_leads_per_month": 1000,
  "expires_at": "2027-01-31T23:59:59Z",
  "features": ["sourcing", "personalization", "analytics"]
}
```

Payload rules:

- `customer` and `plan` must be non-empty strings.
- `max_mailboxes` and `max_leads_per_month` must be positive integers.
- `expires_at` must parse as a timezone-aware RFC 3339 UTC timestamp.
- `features` must be a list of non-empty strings.
- Reject booleans as integers.
- Reject missing claims, duplicate JSON keys, unknown encoding, malformed base64,
  wrong algorithms, and invalid Ed25519 signatures.
- Treat malformed and unverifiable tokens exactly as blocked licenses.

## License API

Keep the implementation beginner-friendly:

```python
class LicenseStatus(BaseModel):
    valid: bool
    in_grace: bool
    expires_at: datetime | None
    reason: str
    customer: str | None = None
    plan: str | None = None
    max_mailboxes: int | None = None
    max_leads_per_month: int | None = None
    features: list[str] = []


class LicenseClaims(BaseModel):
    customer: str
    plan: str
    max_mailboxes: int
    max_leads_per_month: int
    expires_at: datetime
    features: list[str]


def verify_license_token(token: str, public_key_pem: str, now: datetime) -> LicenseStatus:
    ...


async def license_allows_sourcing(db, now: datetime | None = None) -> bool:
    ...


async def license_allows_sending(db, now: datetime | None = None) -> bool:
    ...


async def refresh_license_state(
    db,
    token: str,
    public_key_pem: str,
    now: datetime | None = None,
) -> LicenseStatus:
    ...
```

One source of truth is preferable:

```text
verify token
  -> LicenseClaims + cryptographic validity
  -> LicenseStatus
  -> license state cache
  -> sourcing/sending decision
```

Do not add separate valid/expired booleans to setup or campaign code.

## Enforcement rules

### Expiry and grace

At an explicit UTC `now`:

1. Missing token or public key: blocked.
2. Malformed or invalid signature: blocked.
3. `now <= expires_at`: valid.
4. `expires_at < now <= expires_at + 14 days`: grace mode.
5. `now > expires_at + 14 days`: expired/blocking.

Grace should be a clear dashboard state, not a hidden bypass. The license status
must expose `in_grace=true` and a reason.

### Sending

Update `send_due` to call the real license helper every time it considers a due
enrollment, after suppression and before mailbox/window/cap/send work.

Important order:

```text
kill switch
-> SKIP LOCKED
-> suppression
-> license
-> send window
-> Redis cap
-> send
```

License problems block only that send:

- no mailbox lock;
- no Redis cap reservation;
- no state-machine transition;
- no message or receipt.

Compliance remains independent. Suppressed enrollments must still transition to
`unsubscribed` before the license check.

### Sourcing

Before a source or verification batch that would create new leads:

1. Check license validity or grace.
2. Check the `max_mailboxes` and `max_leads_per_month` limits as applicable.
3. Fail closed on store/database/license errors.
4. Pause the job and expose a clear dashboard alert.

License or source limits must not stop:

- unsubscribe handling;
- suppression imports and lookups;
- bounce and complaint handling;
- reply state transitions;
- suppression-before-wipe forget-person work.

### Campaign and mailbox creation

Campaign creation and mailbox additions are license-sensitive setup actions.
Block them with a clear `LicenseError` when expired, missing, or over limit.
No license check changes an existing enrollment or removes suppression.

## Setup integration

Update `POST /setup/license`:

1. Require an authenticated user.
2. Verify the supplied signed token.
3. Reject malformed, expired beyond grace, or cryptographically invalid tokens.
4. Store the token and update `valid_until` and `last_checked_at`.
5. Never return the stored license token or public key.

The setup endpoint may store an in-grace token and return:

```json
{
  "stored": true,
  "valid": true,
  "in_grace": true,
  "expires_at": "..."
}
```

Do not claim that a missing or invalid token is valid.

## Daily license job

Add an idempotent `license_check` ARQ entry point:

1. Load the latest `LicenseState`.
2. If no row or token is blank, refresh the state to blocked and return.
3. Verify the token with the embedded public key.
4. Update `valid_until` and `last_checked_at` only for successfully parsed claims.
5. On invalid input, keep or remove the raw token according to setup policy, but
   return an explicit blocked status.
6. Never call a network endpoint.

Register the job in ARQ settings and use a daily cron schedule. Keep compliance
and send jobs independent of license-job success.

## System status

Use a small authenticated license status endpoint under `/system/license`:

- `valid`
- `in_grace`
- `expires_at`
- `last_checked_at`
- `customer`
- `plan`
- `max_mailboxes`
- `max_leads_per_month`
- `features`
- `reason`

Do not return `token`, public-key material, or unredacted database rows.

Module 13 may render this status; Module 11 only provides the API and helper.

## Tests

Create focused `tests/test_license.py`:

### Cryptographic verification

- A valid Ed25519 signature verifies.
- A tampered payload is rejected.
- A wrong public key is rejected.
- A missing public key fails closed.
- An unsigned three-part token is rejected.
- `alg` must be `EdDSA`.
- Payload with duplicate JSON keys is rejected.
- Missing or malformed claims are rejected.
- Booleans are rejected for integer fields.
- Invalid expiry formats are rejected.
- Unknown extra claims do not bypass required claims.

### Enforcement

- A token is valid before `expires_at`.
- Exactly at `expires_at` is valid.
- The 14-day grace boundary is valid/in-grace.
- One instant past grace is expired/blocking.
- Missing state blocks sends and sourcing.
- Invalid signature blocks sends and sourcing.
- License helper does not change enrollment status or suppression.
- Mailbox limit blocks a new mailbox but does not remove existing mailboxes.
- Monthly lead limit blocks sourcing beyond the exact limit.
- A cap/store failure fails closed for sourcing and send decisions.

### Integration

- `send_due` does not send under a missing or expired license.
- `send_due` still processes suppression and bounce/compliance paths.
- Setup stores only a verifiable token.
- Setup never returns the token or public key.
- The daily license job is idempotent.
- License reruns update `last_checked_at` and do not add duplicate rows.

### Safety

- No test performs network I/O.
- No test uses a real license or private signing key.
- No test sends real email or contacts a real provider.
- Full or partial token values are not written to test logs.

## Implementation order

1. Add `LICENSE_PUBLIC_KEY_PEM` to settings and `.env.example`.
2. Add `app/services/license/license.py` with Pydantic claims/status models.
3. Implement strict JWS parsing and Ed25519 verification.
4. Implement UTC grace and missing/invalid license decisions.
5. Add cache read/update helpers for `LicenseState`.
6. Update `/setup/license` to verify before storing.
7. Update `send_due` to call the real license helper after suppression.
8. Add license gates to future source/campaign/mailbox creation surfaces.
9. Add `/system/license` status without exposing the token.
10. Add the daily `license_check` ARQ entry point and cron.
11. Add focused license tests and rerun Module 5 send tests.
12. Run the full backend suite and confirm compliance paths remain green.
13. Update `PROGRESS.md` and `README.md`.

## Acceptance checklist

- [x] Ed25519 `EdDSA` signatures verify only with the embedded public key.
- [x] Required customer, plan, limit, expiry, and feature claims are validated.
- [x] Malformed, missing, and invalid signatures fail closed.
- [x] A 14-day grace period is applied only after valid expiry.
- [x] Missing or expired licenses block sourcing and new sends.
- [x] Existing suppression, unsubscribe, bounce, and reply behavior continues.
- [x] `send_due` performs the license check after suppression and before send.
- [x] License checks never change enrollment status or create send side effects.
- [x] Source and mailbox limits are enforced from claims.
- [x] `LicenseState.valid_until` and `last_checked_at` are updated correctly.
- [x] Setup stores no invalid token and returns no token or public key.
- [x] `/system/license` returns only redacted status fields.
- [x] The `license_check` ARQ job is idempotent and offline.
- [x] Tests cover signature, expiry, grace, send, sourcing, cache, and compliance.
- [x] Full pytest suite passes.
- [x] `PROGRESS.md` marks Module 11 done and points to Module 12.

## Risks to watch

- **Compliance coupling:** Never place license checks before suppression or
  unsubscribe handling.
- **Unsigned/dev bypass:** There must be no fallback to `valid=true` for missing
  configuration or invalid signatures.
- **Public-key distribution:** The public key is not secret, but shipping the wrong
  key permanently blocks valid licenses. Document key rotation before releases.
- **Expiry clock:** Normalize all timestamps and current time to UTC; never compare
  naive datetimes.
- **Grace ambiguity:** Display whether the deployment is in grace and why it is
  blocked after grace.
- **Token secrecy:** License tokens may contain customer information. Do not return
  or log the full token.
- **Limit races:** Use database or application serialization when enforcing
  monthly lead and mailbox limits; do not rely only on a read-before-create check.
- **Future sends:** A license block is a soft pause, not an enrollment status change.
*** Update File: C:\Asadullah AI\lead-agent\PROGRESS.md
