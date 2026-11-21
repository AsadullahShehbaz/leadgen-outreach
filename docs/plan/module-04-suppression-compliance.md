# Module 4 Plan - Suppression + Compliance

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 10 (suppression table),
16-18 (inbox/compliance rules), and 22 (module 4).
Acceptance test from the design: **suppressed email never sent**.

## Goal

Create small, pure-Python compliance helpers that Module 5 and Module 6 can use:

1. **Suppression** - normalize and hash an email, add permanent suppression rules, and
   check an exact address or its domain before sending.
2. **Footer builder** - refuse to build an email unless sender identity and postal address
   are present, and return a mandatory opt-out footer.
3. **Country rules** - block or allow a lead from being contacted based on country,
   campaign mode, and lawful-basis record.
4. **Forget person** - suppress the address and wipe the lead's personal fields through
   a small fakeable store interface.

This module does not use Supabase or Redis. Tests use in-memory fake stores and no
network calls. No migration is required.

## Out of scope

- `send_due`, mailbox selection, Redis limiter calls, SMTP sending, and kill switch.
- HTTP `/compliance` endpoints.
- Bounce parsing and inbox reply classification (Module 6).
- Email message building, `List-Unsubscribe` headers, or ARQ workers.
- State-machine calls for `unsubscribed` / `bounced`; Module 5 and Module 6 remain
  responsible for enrollment status changes through `transition()`.
- License checks and spend caps.

## Decisions

| Question | Decision |
|---|---|
| Suppression storage | Store only an SHA-256 hash of the normalized email in production; never store the plain email in `Suppression.email_hash`. |
| Email normalization | Strip outer whitespace and lowercase the full address. |
| Domain format | Normalize domains to lowercase, remove a trailing dot, and strip a leading `@`. |
| Domain suppression | A suppression record may include a domain; exact email hash and domain matches both suppress contact. |
| Duplicate suppression | Adding the same email again is idempotent and must not create a duplicate row. |
| Footer fields | Both `sender_identity` and `postal_address` are mandatory; missing values raise `ValueError`. |
| Country blocking | Germany and Canada remain blocked unless a supported lawful basis is supplied. |
| Unknown country | Allow it only when the caller supplies a non-empty lawful-basis value; missing data is not allowed for strict campaign mode. |
| Forget-person scope | Suppress first, then wipe personal fields through a fakeable store. The original suppression hash must remain after wiping. |

## Deliverables

```text
backend/
  app/services/compliance/
    suppression.py       # NEW: normalization, hashing, SuppressionStore, suppression functions
    footer.py            # NEW: mandatory sender and postal-address footer builder
    rules_by_country.py  # NEW: country and lawful-basis rules
    forget_person.py     # NEW: suppress and wipe person details
    __init__.py          # existing package file
  tests/
    test_suppression.py
    test_footer.py
    test_country_rules.py
    test_forget_person.py
docs/plan/
  module-04-suppression-compliance.md
PROGRESS.md
README.md
```

No API schemas or routers are added in this module.

## Suppression API

Use a tiny protocol instead of importing SQLAlchemy in the compliance logic:

```python
class SuppressionStore(Protocol):
    async def add(self, email_hash: str, domain: str | None, reason: str) -> None: ...
    async def find_email(self, email_hash: str) -> bool: ...
    async def find_domain(self, domain: str) -> bool: ...

def normalize_email(email: str) -> str: ...
def hash_email(email: str) -> str: ...
def domain_from_email(email: str) -> str: ...
async def add_suppression(store, email, reason) -> str: ...
async def is_suppressed(store, email) -> bool: ...
```

Behavior:

- `normalize_email("")` and malformed addresses raise `ValueError`.
- For this module, a valid address has a non-empty local part and exactly one `@` with
  a non-empty domain.
- Hashing is SHA-256 hex digest with no salt.
- `add_suppression()` stores one exact-address record by `email_hash` and also stores
  `domain_from_email(email)`.
- `is_suppressed()` fails closed: invalid email addresses return `True`. A
  `SuppressionStore` error is raised so the caller does not send; Module 5 must treat
  lookup failure as blocked.
- Repeated `add_suppression()` calls are idempotent at the store level.
- The exact email hash and domain are both checked. A domain-level rule suppresses every
  address at that domain.

The table model already has `email_hash`, `domain`, `reason`, and `at`. No model change
is required for exact-address suppression.

## Footer API

```python
def build_footer(sender_identity: str | None,
                 postal_address: str | None,
                 opt_out_url: str) -> str:
    ...
```

Behavior:

- Strip whitespace on both required fields.
- Reject missing sender identity or postal address with `ValueError`.
- Reject a missing/blank `opt_out_url` with `ValueError`.
- Footer includes sender identity, postal address, and a working opt-out instruction.
- Example shape:

```text
{sender_identity}
{postal_address}

Not interested? Unsubscribe: {opt_out_url}
```

The URL is passed in by the caller; the footer builder never invents a link or reads
environment secrets. The actual one-click `List-Unsubscribe` header is deferred to
Module 5 message building.

## Country rules

```python
SUPPORTED_LAWFUL_BASES = {
    "consent",
    "legitimate_interest",
    "express_consent",
    "implied_exception",
}

def can_contact(country: str | None,
                lawful_basis: str | None,
                compliance_mode: str = "standard") -> tuple[bool, str]:
    ...
```

The design is intentionally simpler here:

- Normalize country as a two-letter uppercase code when possible.
- `standard` campaign mode:
  - US allows outreach because B2B prior consent is not required under the design
    guardrail, provided the lead has a recorded source and lawful-basis value if the
    caller supplies those fields.
  - Germany requires `consent`.
  - Canada requires `express_consent` or `implied_exception`.
  - EU/UK require `consent` or `legitimate_interest`.
  - Unknown country requires a supported, non-empty lawful basis.
- `strict` campaign mode requires a supported lawful basis for every country, plus the
  country-specific rule above.
- Unsupported country strings fail with an explicit `ValueError` rather than silently
  allowing contact.
- Unknown lawful-basis strings fail with an explicit `ValueError`.
- Return `(False, reason)` for blocked contact and `(True, "")` for allowed contact.

Campaign `compliance_mode` remains `draft/status` data. This module only evaluates it.

## Forget-person API

```python
class LeadForgetStore(Protocol):
    async def forget_lead(self, lead_id: str, email: str) -> None: ...

async def forget_person(store, suppression_store, lead_id, email) -> None:
    await add_suppression(suppression_store, email, "forget")
    await store.forget_lead(lead_id, email)
```

The fake and production store implementations decide exactly which database fields to
wipe. The process must remain:

1. Add/confirm permanent suppression.
2. Wipe person name, title, country, lawful basis, raw source payload, and LeadEmail
   email for the matching person.
3. Keep campaign/company aggregates and the lead row so audit and campaign statistics
   stay structurally usable.

No enrollment status transition is performed here. The suppressed address will block
future sends, and Module 5 re-checks suppression on every send.

## Tests

`tests/test_suppression.py`

- Normalization strips whitespace and lowercases the address.
- Valid email with exactly one `@` passes.
- Missing local/domain, extra `@`, and blank input raise `ValueError`.
- SHA-256 output is stable and lowercase hex.
- Exact address is suppressed after `add_suppression()`.
- Domain-only record suppresses another address at the same domain.
- Adding the same address twice does not create duplicates.
- Different addresses and domains remain independent.
- Plain email text is never accepted as a stored hash.

`tests/test_footer.py`

- Complete identity and address produce a footer containing both and the opt-out URL.
- Missing sender identity or postal address raises `ValueError`.
- Missing/blank opt-out URL raises `ValueError`.
- Whitespace-only values fail; surrounding whitespace is trimmed.

`tests/test_country_rules.py`

- US allows contact with a supported basis.
- US with missing/unknown basis is blocked or raises as defined.
- Germany requires `consent`.
- Canada requires `express_consent` or `implied_exception`.
- EU/UK require `consent` or `legitimate_interest`.
- Strict mode requires a lawful basis for every country.
- Unknown country and unknown lawful-basis values fail loudly.
- Missing compliance mode defaults to `"standard"` without inventing a rule.

`tests/test_forget_person.py`

- Suppression is added before personal fields are wiped.
- The stored address hash remains even after a fake lead store has wiped email text.
- Domain/other addresses are checked as specified.
- Missing email or lead ID raises `ValueError`.
- Suppression and wipe failure behavior is visible; neither function silently reports success.

## Implementation order

1. Add `app/services/compliance/suppression.py` and `test_suppression.py`.
2. Add `footer.py` and `test_footer.py`.
3. Add `rules_by_country.py` and `test_country_rules.py`.
4. Add `forget_person.py` and `test_forget_person.py`.
5. Update package exports only if they remain small and beginner-friendly.
6. Run the focused Module 4 suite, then the full backend suite.
7. Update `PROGRESS.md` and `README.md`.

Run focused tests:

```powershell
cd "C:\Asadullah AI\lead-agent\backend"
venv\Scripts\python.exe -m pytest -q tests/test_suppression.py tests/test_footer.py tests/test_country_rules.py tests/test_forget_person.py
```

Run the full suite:

```powershell
cd "C:\Asadullah AI\lead-agent\backend"
venv\Scripts\python.exe -m pytest -q
```

## Acceptance checklist

- [x] Exact suppressed email hashes are found before any send.
- [x] Domain-level suppression rules block addresses on that domain.
- [x] Duplicate suppression is idempotent.
- [x] Empty, malformed, or unknown compliance input fails explicitly.
- [x] Missing sender identity or postal address prevents footer generation.
- [x] Germany and Canada require their supported lawful bases.
- [x] Forget-person suppresses before wiping personal fields.
- [x] No real database, Redis, network, or email account is used by tests.
- [x] Full test suite remains green.
- [x] `PROGRESS.md` and `README.md` reflect Module 4 completion.

## Risks to watch

- **Never compare plaintext email values in production SQL.** Hash normalized addresses
  and use the existing unique `Suppression.email_hash` field.
- **Suppression lookup failure must not send.** Module 5 must treat lookup failure as
  "blocked" until the compliance store is available.
- **A domain rule can be broader than a bounce.** Domain rows are appropriate only for
  explicit rules that should block every address at that domain.
- **Footer is compliance-critical.** Missing setup fields must produce an error, never
  an email body without sender identity or postal address.
- **Country rules are guardrails, not legal advice.** Keep values explicit and document
  that a lawyer must review campaign policies before selling.
- **Keep the module simple.** It should contain plain functions and small protocols,
  without workers, API dependencies, or database sessions.
