# Module 1 Plan — Data Models + Migrations

Status: implemented in code (2026-11-19). Live database steps are pending until the Supabase URLs are added to `backend/.env`.
Date: 2026-11-19
Design reference: `docs/leadgen-system-design-v2.md`, Sections 10 and 22 (module 1).

## Goal

Create all 16 tables from design Section 10 as SQLModel classes, an async Postgres session, and an Alembic initial migration that applies cleanly to an empty database.

Acceptance (Section 22): `alembic upgrade head` succeeds on an empty Postgres database, `downgrade base` reverses it, `upgrade head` works again, and `pytest` passes.

Out of scope: routers, auth, Redis, workers, business logic, state machine, DB checks in `/health`.

## Locked decisions

- **Database:** Supabase free cloud Postgres (no local Docker/Postgres on this machine). Use the **Session pooler** (port 5432) for the app and Alembic; the direct host is IPv6-only by default and the transaction pooler (port 6543) is unsuitable for migrations.
- **Primary keys:** UUID, generated in Python with `uuid4` (stdlib; no `pgcrypto`).
- **Migrations tested:** integration test included, running against a separate test-only Supabase project.
- **Times:** UTC everywhere, `DateTime(timezone=True)`, Python-side defaults (`utcnow`), no DB triggers.
- **Statuses:** plain strings, not Postgres enums (easy to extend; the state machine validates transitions later).
- **JSON columns:** Postgres `JSONB`, `server_default "'{}'::jsonb"` where noted.
- **Constraint naming:** shared `MetaData` with a naming convention (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`) so future Alembic diffs stay stable.
- **`workspace_id`:** only on tables the design lists — users, connections, domains, mailboxes, campaigns, leads.

## Deliverables

```
backend/
  .env                      # local secrets, gitignored (created with placeholder, filled by user)
  .env.example              # DATABASE_URL / TEST_DATABASE_URL placeholders, no real secrets
  pytest.ini                # asyncio_mode=auto, testpaths=tests, integration marker
  alembic.ini               # no URL here; env.py decides
  alembic/
    env.py                  # async migrations; URL from config or settings
    script.py.mako
    versions/<rev>_initial_schema.py
  app/core/
    config.py               # Settings (pydantic-settings) + normalize_database_url()
    db.py                   # shared MetaData, async engine, session factory, get_session()
  app/models/
    base.py                 # naming convention, utcnow(), JSONB helper
    workspace.py            # Workspace, User
    connection.py           # Connection
    domain.py               # Domain, Mailbox
    campaign.py             # Campaign, SequenceStep
    lead.py                 # Lead, LeadEmail
    enrollment.py           # Enrollment, Message, Event
    suppression.py          # Suppression
    analytics.py            # Experiment, SpendLedger
    license.py              # LicenseState
    __init__.py             # imports every model module so metadata is complete
  tests/
    test_models.py          # metadata-level checks, no database needed
    test_config.py          # URL normalization cases
    test_migrations.py      # Alembic upgrade/downgrade/upgrade against TEST_DATABASE_URL
root/
  .gitignore                # venv/, .venv/, .env, __pycache__, .pytest_cache, node_modules/
```

`alembic_version` (17th table) is managed by Alembic.

## Supabase URL handling

Supabase's Session pooler string looks like (IPv4-safe):

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Use the Session pooler (port 5432). The direct host (`db.<project-ref>.supabase.co`) is IPv6-only by default, and the transaction pooler (port 6543) breaks DDL and prepared statements — never use it for Alembic.

asyncpg does not accept `sslmode` or `channel_binding`. `normalize_database_url()` in `app/core/config.py`:

1. Force scheme to `postgresql+asyncpg://` (accept `postgres://` and `postgresql://`).
2. Map `sslmode=require` to `ssl=require`.
3. Remove `channel_binding` and `pgbouncer` if present.
4. Leave everything else untouched.

Rules:

- `backend/.env` holds the real URLs and is gitignored.
- Real credentials are never pasted into chat, logs, tests, or committed files.
- `TEST_DATABASE_URL` comes from a **separate Supabase project** used only for tests (the free tier allows two projects).

## Table summary

Notation: `?` = nullable. All tables have an `id` UUID primary key and `created_at` unless noted.

| Table | Columns (beyond id/created_at) | Constraints/indexes |
|---|---|---|
| workspaces | name, sender_identity?, postal_address?, footer_text?, timezone="UTC", updated_at | — |
| users | workspace_id, email, password_hash, role="admin", totp_secret? | uq(workspace_id,email), ix(workspace_id) |
| connections | workspace_id, kind, encrypted_secret, status="unconfigured" | ix(workspace_id) |
| domains | workspace_id, name, spf_ok/dkim_ok/dmarc_ok=false, warmup_started_at? | uq(workspace_id,name), ix(workspace_id) |
| mailboxes | workspace_id, domain_id, address, daily_cap=40, status="warming", health_score=100 | uq(workspace_id,address), ix(workspace_id), ix(domain_id) |
| campaigns | workspace_id, name, product {}, icp {}, status="draft", compliance_mode="standard", require_approval=true | ix(workspace_id) |
| sequence_steps | campaign_id, step_no, delay_days=3, angle_hint? | uq(campaign_id,step_no), ix(campaign_id) |
| leads | workspace_id, source, company_domain?, company_name?, person_name?, title?, country?, icp_score?, lawful_basis?, collected_at, raw {} | ix(workspace_id,company_domain) |
| lead_emails | lead_id, email, verify_status="unknown", verified_at?, role_based=false | uq(lead_id,email), ix(lead_id), ix(email) |
| enrollments | campaign_id, lead_id, lead_email_id, mailbox_id?, status="new", step_no=0, next_send_at?, variant_id? | ix(status,next_send_at), uq(campaign_id,lead_id), ix(campaign_id), ix(lead_id), ix(lead_email_id), ix(mailbox_id) |
| messages | enrollment_id, direction, message_id?, in_reply_to?, thread_id?, subject, body (Text), variant_id?, sent_at? | ix(enrollment_id), ix(message_id) |
| events | enrollment_id, type, payload {}, at | ix(enrollment_id) |
| suppression | email_hash UNIQUE, domain?, reason, at | uq(email_hash) |
| experiments | campaign_id, kind, variants {}, stats {} | ix(campaign_id) |
| spend_ledger | day, kind, units=0, est_usd=0 | ix(day,kind) |
| license_state | token, valid_until?, last_checked_at? | — |

Notes:

- `id: uuid.UUID = Field(default_factory=uuid4, primary_key=True)`; foreign keys typed `uuid.UUID`.
- JSONB columns use a helper that builds `Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))`.
- `collected_at`, `at`, `sent_at`, `verified_at`, `next_send_at`, `valid_until`, `last_checked_at`, `warmup_started_at` are timezone-aware.
- Indexes on `enrollments(status, next_send_at)`, `suppression(email_hash)` (unique), `messages(message_id)`, `leads(workspace_id, company_domain)` are required by Section 10.

## Implementation order

1. Root `.gitignore`; `backend/.env.example`; `config.py` with `Settings` (only `database_url` for now) and `normalize_database_url()`.
2. `models/base.py`: naming convention, `utcnow()`, JSONB helper.
3. Model files in dependency order: workspace → connection → domain → campaign → lead → enrollment → suppression → analytics → license; import all in `models/__init__.py`.
4. `db.py`: async engine (`pool_pre_ping=True`), `async_sessionmaker(expire_on_commit=False)`, `get_session()`.
5. `alembic init -t async alembic`; edit `alembic.ini` (no hardcoded URL) and `env.py`:
   - URL = `config.get_main_option("sqlalchemy.url")` if set, else `settings.database_url`.
   - `target_metadata` = metadata from `app.models`.
6. `alembic revision --autogenerate -m "initial schema"`; then **read the generated migration line by line** and fix anything missed (server defaults, indexes, uniques, JSONB, UUID types).
7. Apply to the dev database: `upgrade head` → inspect → `downgrade base` → `upgrade head`.
8. Tests:
   - `test_models.py`: exactly 16 tables; required indexes/uniques present; no DB needed.
   - `test_config.py`: URL normalization (Supabase style, plain postgres style, already-asyncpg style).
   - `test_migrations.py`: skip unless `TEST_DATABASE_URL` is set; refuse to run if it equals `DATABASE_URL` or shares its hostname (protects the dev database); run `upgrade head` → assert 16 tables + `alembic_version` → `downgrade base` → assert no app tables → `upgrade head`.
9. Verify `fastapi dev app/main.py` still starts; update `PROGRESS.md` (Module 1 done, next = Module 2).

## User setup steps (outside the code)

1. Create Supabase project A for the app.
2. Project Settings → Database → Connection string → **Session pooler**; copy it.
3. Put it in `backend/.env` as `DATABASE_URL=...`.
4. Create a second Supabase project B, used only for tests.
5. Copy project B's Session pooler string into `backend/.env` as `TEST_DATABASE_URL=...`.

## Acceptance checklist

- [ ] `alembic upgrade head` applies cleanly to the empty Supabase dev database.
- [ ] 16 application tables + `alembic_version` exist.
- [ ] `alembic downgrade base` removes all application tables.
- [ ] `alembic upgrade head` succeeds again.
- [ ] `pytest` passes, including the migration integration test against the separate test project.
- [x] `fastapi dev app/main.py` starts and `/health` still returns `ok`.
- [x] `PROGRESS.md` updated with results and next step.
- [x] `alembic upgrade head --sql` renders valid Postgres DDL (UUID, JSONB, timezones, indexes, named constraints).
- [x] Migration file was generated from the metadata, then reviewed: server defaults, JSONB, UUID, composite uniques, required indexes and drop order all checked.

The first four boxes are the live-database run, blocked only on `backend/.env` not existing yet.

## Implementation notes (2026-11-19)

- No database was reachable, so `0001_initial_schema.py` was rendered from `SQLModel.metadata` against an empty SQLite database (Alembic autogenerate), then normalized: `AutoString` → `sa.String()`, JSONB text type → `sa.Text()`, cleaner JSONB server defaults.
- The rendered Postgres SQL was inspected with `alembic upgrade head --sql`; exit code 0.
- Test results: 9 passed, 1 skipped (`test_migrations.py` waits for `TEST_DATABASE_URL`).
- Constraint names are stable and explicit (`pk_`, `fk_`, `uq_`, `ix_`); composite uniques have full names.
- Minor future issue found, not fixed here: `passlib 1.7.4` + `bcrypt 5` are incompatible; handle in Module 7 (auth).

## Risks to watch

- **Python 3.14 + asyncpg/Supabase:** verify the first real connection early; if it fails, adjust the Python version instead of writing workarounds.
- **Alembic autogenerate** can silently drop indexes/uniques — review the generated migration, never trust it blindly.
- **Duplicate index names** across tables — the naming convention prevents this.
- **Supabase pooling:** use the Session pooler (port 5432) for migrations; never the transaction pooler (port 6543).
- **`.env` leakage** — gitignored before the first commit; no secrets in `.env.example`.
- Not part of Module 1: `passlib 1.7.4` + `bcrypt 5` are incompatible; fix in Module 7 (auth).
