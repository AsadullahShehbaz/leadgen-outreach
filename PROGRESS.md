# Project Progress

Last updated: 2026-11-19

Track what is done so any future session (or coding agent) can pick up where we left off.
Read `docs/leadgen-system-design-v2.md` first, then `docs/leadgen-explained-for-beginners.md` for the beginner overview.

## Current status

Modules 0 and 1 done in code: environment installed, all 16 tables, async session, Alembic initial migration, and tests. Unit tests pass (9 passed); the migration integration test is skipped until `backend/.env` has the Supabase URLs. The live migration (`alembic upgrade head`) has not been run yet. Database will be Supabase (cloud Postgres). No git repo yet.

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
- Every module in the build order (Module 0 added for environment setup, then Section 22):

| # | Module | Status |
|---|---|---|
| 0 | Environment setup (venv + libraries) | Done |
| 1 | Models + migrations | Implemented; live migration pending Supabase URLs |
| 2 | State machine | Not started |
| 3 | Limiter + windows | Not started |
| 4 | Suppression + compliance | Not started |
| 5 | `send_due` + FakeMailProvider | Not started |
| 6 | Inbox worker | Not started |
| 7 | Auth + setup wizard API | Not started |
| 8 | Spend caps + ledger | Not started |
| 9 | Sources + verify | Not started |
| 10 | LangGraph agent | Not started |
| 11 | License | Not started |
| 12 | Packaging | Not started |
| 13 | React dashboard + wizard | Not started |
| 14 | Optimizer + weekly report | Not started |

## Next step

**Finish Module 1 — run against real Supabase.**

1. Copy `backend/.env.example` to `backend/.env`.
2. Fill `DATABASE_URL` with project A's **Session pooler** string.
3. Fill `TEST_DATABASE_URL` with project B's Session pooler string (separate project).
4. Run from `backend/`:
   - `venv\Scripts\alembic.exe upgrade head`
   - `venv\Scripts\python.exe -m pytest -v`
5. Expect: 16 tables + `alembic_version` in project A; all tests incl. the migration round-trip pass.
6. Then mark the acceptance checklist in `docs/plan/module-01-models-migrations.md` and start Module 2 (state machine).

## How to update this file

After each module: tick it in the table, add a short note under "Done" with the date and what changed, and keep "Next step" pointing at the next module in the build order.
