# Project Progress

Last updated: 2026-11-21

Track what is done so any future session (or coding agent) can pick up where we left off.
Read `docs/leadgen-system-design-v2.md` first, then `docs/leadgen-explained-for-beginners.md` for the beginner overview.

## Current status

Modules 0, 1 and 2 done in code: environment installed, all 16 tables, async session, Alembic initial migration, and the enrollment state machine. Unit tests pass (182 passed); the migration integration test is skipped until `backend/.env` has the Supabase URLs. The live migration (`alembic upgrade head`) has not been run yet. The database will be Supabase (cloud Postgres). Git repo initialized.
Module 3 done: Redis-style atomic daily caps and timezone-aware send windows are implemented with fake-Redis and concurrency tests.
Module 4 done: SHA-256 suppression and domain checks, mandatory footer building, country/lawful-basis rules, and forget-person helpers are implemented.
Module 8 done: UTC spend summaries, daily caps, Postgres-backed atomic reservations, and tests are implemented.
Module 10 done: Groq-backed LangGraph personalization, Pydantic drafts, factual critic retries, persisted drafts, approval transitions, and spend-cap gates are implemented.

## Done

- [x] Saved the system design (`docs/leadgen-system-design-v2.md`) and a beginner-friendly explanation (`docs/leadgen-explained-for-beginners.md`).
- [x] Created `AGENTS.md` at the repo root with the project rules from Section 23 plus extra working rules.
- [x] Created `backend/requirements.txt`; created `backend/venv` and installed all packages (Module 0 done).
- [x] Saved the approved Module 1 plan: `docs/plan/module-01-models-migrations.md`.
- [x] Module 1 implemented:
  - `app/core/config.py` (settings + Supabase/asyncpg URL normalization) and `app/core/db.py` (async engine/session).
  - All 16 SQLModel tables in `app/models/` with UUID keys, UTC timestamps, JSONB columns, indexes and named constraints.
  - Alembic set up (`alembic.ini`, async `env.py`, `versions/0001_initial_schema.py`).
  - Tests: `test_models.py`, `test_config.py`, `test_migrations.py` (integration test skips without `TEST_DATABASE_URL`).
  - Verified: `pytest` 9 passed / 1 skipped; `alembic upgrade head --sql` renders valid Postgres DDL; `/health` still returns `ok`.
- [x] Saved the Module 2 plan: `docs/plan/module-02-state-machine.md`.
- [x] Module 2 implemented:
  - `app/services/sequencing/state_machine.py`: `ACTIVE`, `EXIT`, `TERMINAL`, `ALLOWED`, `IllegalTransition`, and `transition()` exactly per Section 11.
  - `transition()` validates before changing anything, clears `next_send_at` on terminal statuses, writes one `Event` per accepted move, and lets the caller commit.
  - `tests/test_state_machine.py`: all 26 allowed moves, all 143 illegal moves, unknown statuses, event payloads, and rulebook consistency; no database needed.
  - Verified: `pytest` 182 passed / 1 skipped; only `state_machine.py` assigns `Enrollment.status`.
- [x] Saved and implemented Module 3:
  - `app/services/sequencing/windows.py`: send-window settings, timezone conversion, workspace-local days, and next-opening calculation.
  - `app/services/sequencing/limiter.py`: atomic Redis counter reservations, 30-hour TTL, independent mailbox/day keys, and slot release.
  - `tests/test_windows.py` and `tests/test_limiter.py`: boundaries, weekends, DST, invalid inputs, independent caps, and concurrent acquires.
  - Verified with the focused Module 3 suite; real-Redis integration runs only when `TEST_REDIS_URL` is configured.
- [x] Saved and implemented Module 4:
  - `app/services/compliance/suppression.py`: normalized SHA-256 email hashing, exact-address checks, domain checks, and idempotent suppression additions.
  - `app/services/compliance/footer.py`: mandatory sender identity, postal address, and opt-out footer.
  - `app/services/compliance/rules_by_country.py`: standard and strict campaign lawful-basis rules.
  - `app/services/compliance/forget_person.py`: suppression-before-wipe forget-person workflow.
  - Added focused suppression, footer, country-rule, and forget-person tests.
  - Verified: `259 passed, 2 skipped`.
- [x] Saved and implemented Module 5:
  - `app/core/redis.py`: Redis client factory.
  - `app/services/mail/base.py` and `fake.py`: provider interface and no-network fake.
  - `app/services/sequencing/send_due.py`: kill switch, locks, suppression, license,
    mailbox, window, daily-cap, send, receipt, and state-advance flow.
  - `app/workers/arq_settings.py` and `jobs.py`: ARQ worker and one-minute cron.
  - Added provider and send-engine tests.
  - Verified: `268 passed, 2 skipped`.
- [x] Saved and implemented Module 6:
  - `app/services/mail/bounce_parser.py`: pure DSN 4.x.x / 5.x.x parsing.
  - `app/services/mail/base.py` and `fake.py`: inbound mail types and no-network fake fetching.
  - `app/services/agents/reply_classifier.py`: fakeable reply classifier interface.
  - `app/services/sequencing/inbox_worker.py`: replay-safe thread matching, replies,
    bounces, suppression, complaint handling, and mailbox penalties.
  - `app/workers/jobs.py` and `arq_settings.py`: three-minute inbox polling cron.
  - Added bounce-parser and inbox-worker tests.
  - Verified: `279 passed, 2 skipped`.
- [x] Saved and implemented Module 7:
  - `app/core/security.py`: direct bcrypt password hashing, HS256 JWT, Fernet secret encryption,
    and Redis-backed token revocation helpers.
  - `app/routers/auth.py`: OAuth2 password login, current-user lookup, logout, and password change.
  - `app/routers/setup.py`: first-run admin/workspace setup, license storage, encrypted
    connections, domain setup, and warming-status mailbox setup.
  - `app/models/workspace.py` and migration `0002_setup_audit.py`: setup responsibility/completion audit fields.
  - Added focused auth, setup, and model tests.
  - Verified: `293 passed, 2 skipped`; both Alembic migrations render valid Postgres SQL.
- [x] Saved and implemented Module 8:
  - `app/core/config.py` and `.env.example`: daily LLM, verification, and source limits; zero disables paid work.
  - `app/services/budget/spend_caps.py`: validated spend checks, ledger recording, UTC summaries,
    and transaction-locked Postgres reservations.
  - `tests/test_spend_caps.py`: cap boundaries, invalid inputs, concurrent fake reservations,
    summaries, store errors, and SQL store behavior.
  - Verified: `307 passed, 2 skipped`; Alembic SQL rendering still passes.
- [x] Saved and implemented Module 9:
  - `app/services/sources/`: CSV and public website sources, fake source, workspace-scoped dedupe, and ICP scoring.
  - `app/services/verify/`: syntax, role-based, MX, catch-all, API/verifier adapters, fake verifier, and spend-gated persistence.
  - ARQ entry points for source and verification jobs are registered.
  - Added focused source, verifier, and pipeline tests.
  - Verified: `317 passed, 2 skipped`.
- [x] Saved and implemented Module 10:
  - `app/services/agents/llm.py`: Groq is the default OpenAI-compatible provider, with a fake LLM for tests.
  - `app/services/agents/research.py`: fakeable bounded research interface.
  - `app/services/agents/personalize_graph.py`: LangGraph score/research/angle/draft/critic/save workflow,
    Pydantic `Draft` validation, local claim support checks, at-most-two retries, human-review fallback,
    persisted enrollment drafts, and state-machine transitions.
  - `app/models/enrollment.py` and migration `0003_personalization_draft.py`: nullable JSONB draft storage.
  - `app/workers/jobs.py`: `personalize` ARQ entry point and worker registration.
  - `tests/test_personalization.py`: draft limits, critic rejection, retry, human review, spend cap,
    approval, queued, and idempotency coverage.
  - Verified: `329 passed, 2 skipped`; Groq and all external providers remain uncalled by tests.
- [x] Created the monorepo structure:

```
backend/
  app/
    __init__.py
    main.py            # minimal FastAPI app with a /health endpoint
    core/              # config, db, redis, security, license, branding (empty)
    models/            # SQLModel tables (empty)
    schemas/           # Pydantic schemas (empty)
    routers/           # API endpoints (empty)
    services/          # sources, verify, mail, agents, sequencing, compliance, budget (empty)
    workers/           # ARQ worker settings and jobs (empty)
  tests/               # pytest (empty, has __init__.py)
frontend/              # React dashboard (empty)
deploy/                # compose, Caddyfile, scripts (empty)
docs/                  # design + explainer (done)
AGENTS.md
PROGRESS.md
```

## Decisions made so far

- Layout is `backend/` + `frontend/` at the root; the Python package stays `app`, so imports remain `app.main:app`. Run backend commands from `backend/`.
- Design and explainer live in `docs/`; `AGENTS.md` points to `docs/leadgen-system-design-v2.md`.
- `app/main.py` currently exposes only `GET /health` (used later by Docker health checks and `update.sh`).
- Database: Supabase cloud Postgres, using the Session pooler (port 5432). `TEST_DATABASE_URL` comes from a separate test-only Supabase project.
- Primary keys: UUID (`uuid4` in Python). Statuses are plain strings. Times are UTC (`DateTime(timezone=True)`).

## Not started

- Postgres connection in `backend/.env` (user must create the Supabase projects).
- Redis, Docker setup.
- Module 9 plan saved; implementation not started.
- Every module in the build order (Module 0 added for environment setup, then Section 22):

| # | Module | Status |
|---|---|---|
| 0 | Environment setup (venv + libraries) | Done |
| 1 | Models + migrations | Implemented; live migration pending Supabase URLs |
| 2 | State machine | Done (2026-11-21) |
| 3 | Limiter + windows | Done (2026-11-21) |
| 4 | Suppression + compliance | Done (2026-11-21) |
| 5 | `send_due` + FakeMailProvider | Done |
| 6 | Inbox worker | Done (2026-11-21) |
| 7 | Auth + setup wizard API | Done (2026-11-21) |
| 8 | Spend caps + ledger | Done (2026-11-21) |
| 9 | Sources + verify | Done (2026-11-21) |
| 10 | LangGraph agent | Done (2026-11-21) |
| 11 | License | Not started |
| 12 | Packaging | Not started |
| 13 | React dashboard + wizard | Not started |
| 14 | Optimizer + weekly report | Not started |

## Next step
**Module 11 — License**.

The Module 1 live-database run is still pending and can be done whenever the Supabase
URLs are ready; it does not block Module 11:

1. Copy `backend/.env.example` to `backend/.env`.
2. Fill `DATABASE_URL` with project A's **Session pooler** string.
3. Fill `TEST_DATABASE_URL` with project B's Session pooler string (separate project).
4. Run from `backend/`:
   - `venv\Scripts\alembic.exe upgrade head`
   - `venv\Scripts\python.exe -m pytest -v`
5. Expect: 16 tables + `alembic_version` in project A; all tests incl. the migration round-trip pass.
6. Then mark the acceptance checklist in `docs/plan/module-01-models-migrations.md` and continue with Module 11.

## How to update this file

After each module: tick it in the table, add a short note under "Done" with the date and what changed, and keep "Next step" pointing at the next module in the build order.
