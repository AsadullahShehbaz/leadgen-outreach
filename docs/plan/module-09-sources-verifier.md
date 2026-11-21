# Module 9 Plan - Sources + Verifier

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 3, 10, 12, 13, 15,
and 22 (module 9).
Acceptance test from the design: **full pipeline test with fakes**.

## Goal

Implement lead sourcing and email verification behind simple, testable interfaces:

1. Add `LeadSource`, `RawLead`, `Verifier`, `VerifyResult`, and fake implementations.
2. Add CSV lead import and a read-only public website crawler.
3. Add the verification pipeline for syntax, MX, catch-all, and optional API verification.
4. Reserve source and verification spend through Module 8 before paid or capped work.
5. Deduplicate and persist sourced leads and verified email rows.
6. Run the pipeline as idempotent jobs or small orchestration functions.

## Out of scope

- LangGraph personalization and LLM calls. Module 10 owns personalization.
- Apollo and Apify production implementations. Their interfaces may be seams, but
  real client integrations require separate provider-specific validation.
- License Ed25519 enforcement. Module 11 owns license checks.
- React lead-import screens and lead-management endpoints. Module 13 owns dashboard APIs and UI.
- Sending, inbox polling, and sequence enrollment changes.
- ICP ML, experiments, bandit ranking, or nightly optimization.
- Aggressive crawling, login bypass, CAPTCHA bypass, or scraping domains that prohibit it.
- A shared vendor key or vendor billing reconciliation.

## Decisions

| Question | Decision |
|---|---|
| Source interface | Implement `LeadSource.fetch(query, limit) -> list[RawLead]`. |
| Default sources | CSV import and the public website crawler. |
| Optional sources | Keep Apollo and Apify behind the same interface, but do not add live implementations in this module unless credentials and terms are supplied. |
| CSV format | Accept a header row and known lead fields: `company_name`, `company_domain`, `person_name`, `title`, `email`, `country`, `lawful_basis`. Unknown columns go into `raw`. |
| Website behavior | Fetch public HTML from explicit user-approved URLs only, extract basic company/person fields conservatively, and create no email guess. |
| No-network tests | `FakeLeadSource` and `FakeVerifier` return in-memory values only. |
| Verification checks | Syntax and role-based checks are local; MX lookup is network-free in tests through a DNS seam; API verification is behind `Verifier`. |
| Verification statuses | Only `valid` and a capped share of `risky` continue. `invalid` and `unknown` stop. |
| Unknown status | Fail closed for sending eligibility. Verification status remains `unknown` until evidence exists. |
| Deduplication | Do not duplicate the same lead; dedupe lead emails by `(lead_id, email)`, and avoid a second lead for the same normalized domain plus person name. |
| Source dedupe | CSV and crawler batches use the database plus normalized email/domain/name keys; rerunning the same job must not create duplicate rows. |
| Spend source | A source paid call reserves source units before fetching. Verification reserves one `verify` unit before each provider or batch call. |
| Failed paid call | A reservation remains counted, as defined by Module 8. No automatic refund is attempted. |
| Cap hit | Pause only the source or verification step and raise a structured return value or log alert. Compliance and sending remain independent. |
| Status changes | Lead creation is plain persistence. Do not use `state_machine.py`; no enrollment status change belongs here. |
| ICP scoring | Store a simple transparent score in `Lead.icp_score` from campaign/company/domain/title fields; no ML or invented external score. |
| Lawful basis | Preserve CSV-provided lawful basis, otherwise set `None` until setup or campaign compliance rules are applied. |
| Idempotency | Every job accepts an explicit batch/key value where relevant and reruns without duplicate leads or email rows. |

## Deliverables

```text
backend/
  app/services/
    sources/
      __init__.py          # NEW package
      base.py              # NEW: RawLead and LeadSource protocols
      csv_import.py        # NEW: pure CSV parsing and CSVLeadSource
      website.py           # NEW: public page crawler and website safety checks
      fake.py              # NEW: FakeLeadSource
      pipeline.py          # NEW: source persistence, dedupe, and ICP scoring
    verify/
      __init__.py          # NEW package
      base.py              # NEW: VerifyResult and Verifier protocols
      syntax.py            # NEW: syntax and role-based checks
      mx.py                # NEW: DNS MX seam and implementation
      catchall.py          # NEW: bounded catch-all logic
      api_verifier.py       # NEW: adapter for a client-owned verifier API
      fake.py              # NEW: FakeVerifier
      pipeline.py          # NEW: verify persistence and eligibility decisions
  app/workers/
    jobs.py                # UPDATE: source and verify job entry points
    arq_settings.py        # UPDATE: register jobs as needed
  tests/
    test_sources.py        # NEW
    test_verifier.py       # NEW
    test_lead_pipeline.py   # NEW
docs/plan/
  module-09-sources-verifier.md
PROGRESS.md
README.md
```

No migration is required unless tests reveal that a design-required field is absent.
Do not add a new ledgers table or change `spend_ledger`.

## Interfaces

```python
class RawLead(BaseModel):
    company_name: str | None = None
    company_domain: str | None = None
    person_name: str | None = None
    title: str | None = None
    email: str | None = None
    country: str | None = None
    source: str
    raw: dict = {}


class LeadSource(Protocol):
    name: str
    async def fetch(self, query: dict, limit: int) -> list[RawLead]:
        ...


class VerifyResult(BaseModel):
    status: Literal["valid", "risky", "invalid", "unknown"]
    reason: str
    role_based: bool = False


class Verifier(Protocol):
    async def verify(self, email: str) -> VerifyResult:
        ...
```

Keep Pydantic fields explicit and never accept arbitrary objects in orchestration
code. Providers receive only the minimum needed to perform their call.

## CSV source

Implement a pure parser before database writes:

- Decode UTF-8 text and accept a comma-delimited header.
- Strip surrounding whitespace.
- Normalize domain values without `http://`, `https://`, or paths.
- Normalize email addresses to lowercase for dedupe and lookups.
- Reject a blank row.
- Store unknown fields in `RawLead.raw`.
- Return a clear row number in parsing errors.

`CSVLeadSource.fetch()` should treat `query["csv_text"]` or an uploaded text field as
its input and return at most `limit` leads. File upload and HTTP parsing belong in
Module 13 unless a small private function is needed for tests.

## Website crawler

Add only a bounded public-page crawler:

- Require explicit `http://` or `https://` URLs.
- Reject private, loopback, link-local, and reserved IP targets after DNS resolution.
- Re-check every redirect destination against the SSRF guard.
- Bound response size and HTML parsing work.
- Use a short timeout and a small maximum page count.
- Extract text and links conservatively with BeautifulSoup.
- Never execute JavaScript or submit forms.
- Never infer or invent a person's email without a source field or a verified pattern.

This implementation may extract company name/domain and visible staff names, but it
must make no promises about contact ownership. The returned source remains
`website`.

## Verification pipeline

Add small pure helpers and one orchestration function:

1. Normalize and validate the email syntax.
2. Mark obvious role-based addresses such as `sales@`, `info@`, and `support@`.
3. Perform MX lookup using an injected DNS/HTTP-free seam.
4. Optionally call the provider `Verifier`.
5. Apply result precedence: provider `invalid` or local syntax `invalid` is final;
   provider `valid` is `valid`; catch-all evidence is `risky`; missing evidence is
   `unknown`.
6. Persist `LeadEmail.verify_status`, `verified_at`, and `role_based`.

The pipeline must not mark an unknown or risky result valid merely because DNS
succeeded. `risky` may continue only under a campaign-specific capped share; default
to no risky sends when no cap is supplied.

## Source and verification jobs

Keep orchestration in pure or session-aware functions:

```python
async def source_leads(
    session,
    source: LeadSource,
    query: dict,
    workspace_id,
    limit: int,
    source_store,
) -> dict:
    ...


async def verify_lead_emails(
    session,
    verifier: Verifier,
    lead_email_ids: list,
    verifier_store,
) -> dict:
    ...
```

Before a source fetch or verification call:

1. Build `SpendLimits.from_settings()`.
2. Reserve source or verification usage atomically through Module 8.
3. Commit the reservation before provider/network work.
4. On cap hit, return `paused=true` and no provider call.
5. On store failure, fail closed and never run the provider.

Reservations are estimates and must not be recorded twice.

No source or verification failure may change `Enrollment` status or block
suppression, unsubscribe, bounce, or send-compliance work.

## Persistence and dedupe

Use the existing `Lead` and `LeadEmail` models:

- Store `source`, `raw`, `collected_at`, `lawful_basis`, and normalized company fields.
- Query by workspace and normalized domain; no cross-workspace matching.
- Use existing unique constraints for lead-email dedupe.
- Insert known fields only; do not persist untrusted HTML or secrets.
- If a person/lead already exists, update only the missing or verified fields.
- Commit one batch transaction, or one idempotent transaction per lead.

No API keys or source response bodies may be written to `Lead.raw` if they contain
credentials or secrets. Store only lead-safe provider fields.

## Spend behavior

- Source fetch: reserve one source unit and caller-supplied estimated USD.
- Verification: reserve one verification unit. Estimated USD may be zero or caller-
  supplied; never invent provider pricing.
- Source and verification caps default to disabled at zero.
- `reserve_usage()` is mandatory for concurrent jobs; `record_usage()` is not used
  after an atomic reservation.
- Summary and alert output may include `paused`, kind, used units, and limits.

## Optional Apollo/Apify seam

Do not store plaintext provider secrets in source code or logs. Resolve client-owned
credentials from `Connection.encrypted_secret` through setup's Fernet helpers.

If an adapter is scaffolded:

- It implements `LeadSource`.
- It declares `name`, and records `source="apollo"` or `source="apify"`.
- It accepts only an injected credential/provider object.
- It has a fake test implementation.
- It performs no live call unless explicitly configured with a real client account.

## Workers

If worker entry points are added, use the existing ARQ context and keep them
idempotent:

- `source_leads(ctx)` resolves the selected source and query from the context or
  database, checks source spend, persists rows, and returns a count.
- `verify_email(ctx)` selects unverified lead emails, checks verification spend,
  verifies each row, and returns a count.

Do not add cron jobs that continuously source or verify leads. Source and verify
remain user-triggered or webhook-triggered until Module 13 adds controls.

## Tests

At minimum, add:

1. `test_sources.py`
   - CSV parsing and normalization.
   - Unknown CSV columns remain in `raw`.
   - Invalid or unsafe crawler URLs are rejected.
   - Redirect/private/loopback targets are rejected.
   - Fake source returns at most `limit`.

2. `test_verifier.py`
   - Syntax valid/invalid.
   - Role-based address detection.
   - MX present/absent.
   - Catch-all is risky, never valid.
   - Fake verifier status precedence.
   - Unknown/verifier failure does not become valid.

3. `test_lead_pipeline.py`
   - Full CSV -> source -> fake verify pipeline.
   - Idempotent rerun creates no duplicate leads or lead emails.
   - Domain/person dedupe.
   - Source cap pause makes no source call.
   - Verification cap pause makes no verifier call.
   - Store/provider failure fails closed.
   - Only `valid` and approved `risky` leads remain eligible.
   - No spend reservation is recorded twice.
   - Lead/lead-email persistence is workspace scoped.

Test providers never perform DNS, SMTP, IMAP, HTTP, or real LLM calls.

## Acceptance checklist

- [ ] `RawLead`, `LeadSource`, `VerifyResult`, and `Verifier` are implemented.
- [ ] CSV import parses and normalizes a lead batch.
- [ ] Website crawler rejects unsafe targets and has bounded network behavior.
- [ ] Fake source and fake verifier perform no network I/O.
- [ ] Verification has syntax, MX, catch-all, and optional API seams.
- [ ] Source and verification reserve Module 8 budget before provider work.
- [ ] Cap hits pause only the relevant step.
- [ ] Lead and lead-email persistence is workspace scoped and deduplicated.
- [ ] Full pipeline test passes using fake source, fake DNS, and fake verifier.
- [ ] Rerunning the pipeline does not create duplicate rows or duplicate reservations.
- [ ] No secrets or full provider responses are logged or persisted.
- [ ] `PROGRESS.md` and `README.md` describe Module 9 accurately.
