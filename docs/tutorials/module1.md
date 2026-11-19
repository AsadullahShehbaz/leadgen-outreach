# Build the Data Layer with SQLModel, Alembic, and Supabase Postgres

*Lead Generation Agent, Module 1*

In this tutorial we build the database foundation of the lead generation system described in `docs/leadgen-system-design-v2.md` (Sections 10 and 22).

We turn the 16 tables from the design document into SQLModel classes, connect to a free Supabase Postgres database through an async session, and create an Alembic migration that builds every table on an empty database.

By the end, we can apply the migration, reverse it, apply it again, and prove it with `pytest`.

## 1. What Are We Building in Module 1?

The module delivers:

- 16 SQLModel table classes in `backend/app/models/`
- An async Postgres engine and session in `backend/app/core/db.py`
- Settings with Supabase URL normalization in `backend/app/core/config.py`
- One Alembic initial migration: `backend/alembic/versions/0001_initial_schema.py`
- Tests for models, URL normalization, and the migration round-trip

The acceptance sequence is:

```
alembic upgrade head
alembic downgrade base
alembic upgrade head
pytest
```

Out of scope for this module: routers, auth, Redis, workers, business logic, the state machine, and database checks inside `/health`. Those come later.

## 2. How the Data Layer Will Work

```
   SQLModel classes (our tables)
              |
              |  alembic revision --autogenerate   (or a reviewed offline draft)
              v
   Migration file (upgrade / downgrade)
              |
              |  alembic upgrade head
              v
   Supabase Postgres (Session pooler, port 5432)
              ^
              |  async session (asyncpg)
              |
   FastAPI app (later modules)
```

The models describe the desired schema. Alembic turns the difference between the models and the database into a migration file. The app talks to the same database through an async session.

## 3. Decisions We Locked Before Writing Code

| Topic | Decision | Why |
| --- | --- | --- |
| Database | Supabase free cloud Postgres | No local Postgres or Docker on this machine |
| Connection | Session pooler, port 5432 | Direct host is IPv6-only by default; transaction pooler (6543) breaks migrations |
| Primary keys | UUID generated in Python with `uuid4` | Standard library only, no `pgcrypto` extension |
| Times | UTC, `DateTime(timezone=True)`, Python-side defaults | One clock everywhere, no database triggers |
| Statuses | Plain strings, not Postgres enums | Easy to extend; the state machine validates transitions later |
| JSON columns | Postgres `JSONB` with a `'{}'::jsonb` default | Flexible data with a safe empty default |
| Constraint names | Naming convention plus explicit composite names | Future Alembic diffs stay stable and readable |
| `workspace_id` | Only on users, connections, domains, mailboxes, campaigns, leads | Exactly what the design lists |
| Indexes | Only where a real query needs them | Indexes speed reads but slow writes and use storage |

## 4. Set Up Two Supabase Projects

We need two separate Supabase projects:

- Project A: the app (development) database
- Project B: used only by the migration test

Why two? The migration test runs `upgrade`, `downgrade`, and `upgrade` again. A downgrade deletes tables. That must never touch development data. The free tier allows two projects.

For each project:

1. Open Project Settings, then Database, then Connection string.
2. Choose the Session pooler string.
3. Copy it.

A Session pooler string looks like this:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Rules:

- Always use port 5432 (Session pooler) for the app and Alembic.
- Never use port 6543 (Transaction pooler) for migrations. DDL and prepared statements break there.
- Never paste real credentials into chat, logs, tests, or committed files. They live only in `backend/.env`.

## 5. Prepare the Project Folder

After Module 1 the project looks like this:

```
root/
├── .gitignore
└── backend/
    ├── .env                  # real secrets, gitignored
    ├── .env.example          # placeholders only
    ├── pytest.ini
    ├── requirements.txt
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       └── 0001_initial_schema.py
    ├── app/
    │   ├── main.py
    │   ├── core/
    │   │   ├── config.py
    │   │   └── db.py
    │   └── models/
    │       ├── __init__.py
    │       ├── base.py
    │       ├── workspace.py
    │       ├── connection.py
    │       ├── domain.py
    │       ├── campaign.py
    │       ├── lead.py
    │       ├── enrollment.py
    │       ├── suppression.py
    │       ├── analytics.py
    │       └── license.py
    └── tests/
        ├── test_models.py
        ├── test_config.py
        └── test_migrations.py
```

Create the root `.gitignore` before the first commit, so secrets can never leak:

```
# Python
venv/
.venv/
__pycache__/
*.py[cod]
.pytest_cache/

# Secrets
.env
!.env.example

# Frontend
node_modules/
dist/

# Build artifacts
build/
*.egg-info/
```

Install dependencies inside the virtual environment. On Windows `cmd`:

```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

The file includes `fastapi[standard]` (which provides the `fastapi dev` command), `sqlmodel`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`, `pytest`, and `pytest-asyncio`, plus the later-module dependencies.

A note about Python 3.14: test a real database connection early, in Section 12. If asyncpg fails to connect, change the Python version instead of writing workarounds.

## 6. Write the Config and URL Normalizer

Supabase gives a `postgresql://...?sslmode=require` URL, but asyncpg understands neither `sslmode` nor `channel_binding`. The config normalizes it automatically.

Create `backend/app/core/config.py`:

```python
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Turn a plain Postgres URL into one asyncpg can use.

    Supabase gives URLs like:
        postgresql://user:pass@host:5432/postgres?sslmode=require&channel_binding=require

    asyncpg does not understand "sslmode" or "channel_binding", so we rewrite
    the scheme and the query string before passing it to SQLAlchemy.
    """
    url = url.strip()

    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in ("channel_binding", "pgbouncer"):
            continue
        if key == "sslmode":
            key = "ssl"
        query.append((key, value))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Placeholder so the app can start before .env exists.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Used only by the migration integration test.
    test_database_url: str | None = None

    @property
    def async_database_url(self) -> str:
        return normalize_database_url(self.database_url)


settings = Settings()
```

What `normalize_database_url()` does:

1. Convert a plain `postgres://` or `postgresql://` scheme to `postgresql+asyncpg://`.
2. Map `sslmode=require` to `ssl=require`, which asyncpg accepts.
3. Remove `channel_binding` and `pgbouncer`, which asyncpg rejects.
4. Leave an already-normalized URL unchanged.

Why is there a default `database_url`? So importing the app, or running the URL tests, never crashes before `.env` exists. The real value still comes from `.env`. The `async_database_url` property normalizes lazily, only when something asks for a connection string.

## 7. Create the Environment Files

Create `backend/.env.example` with placeholders only:

```
# Copy this file to backend/.env and fill in the real values.
# Never commit .env. Never share these URLs or passwords.

# Supabase -> Project Settings -> Database -> Connection string -> Session pooler
# Use port 5432 (Session pooler), not 6543 (transaction pooler).
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require

# Separate Supabase project used ONLY by the migration integration test.
TEST_DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Copy it to `.env` and fill in both Session pooler strings:

```
cp .env.example .env
```

Verify Git ignores the real file (run from the root):

```
git check-ignore backend/.env
```

If it prints the path, the file is ignored and safe.

## 8. Write the Model Helpers

Create `backend/app/models/base.py`:

```python
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# Stable names for primary keys, foreign keys, uniques and indexes.
# Without this, Alembic creates random constraint names and future
# migrations become noisy.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def apply_naming_convention() -> None:
    # Must run before any table class is created (see app/models/__init__.py).
    SQLModel.metadata.naming_convention = NAMING_CONVENTION


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    """Adds a UTC created_at column to every table."""

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


def jsonb_column(default_sql: str = "'{}'::jsonb") -> Column[Any]:
    # JSONB holds flexible per-record data (raw source payloads, campaign
    # product/ICP, experiment variants). The server default keeps raw SQL
    # inserts valid too.
    return Column(JSONB, nullable=False, default=dict, server_default=text(default_sql))


def tz_column(*, nullable: bool = True) -> Column[Any]:
    """A timezone-aware timestamp column stored in UTC."""
    return Column(DateTime(timezone=True), nullable=nullable)
```

Understanding each part:

- `NAMING_CONVENTION` gives constraints predictable names: `pk_users`, `fk_users_workspace_id_workspaces`, `ix_users_...`. Without it, Postgres invents names and future Alembic diffs become noisy.
- `apply_naming_convention()` must run before the first table class is created, because names are assigned when the class is defined. `app/models/__init__.py` calls it first.
- `utcnow()` is the single source of time. It returns a timezone-aware UTC datetime.
- `TimestampMixin` adds `created_at` to every table, so we write it once.
- `jsonb_column()` returns a fresh JSONB column each call. A SQLAlchemy `Column` object cannot be shared between tables.
- `tz_column()` builds a nullable `TIMESTAMP WITH TIME ZONE` column for optional timestamps.

## 9. Create the 16 Models

The tables fall into groups:

| Group | Tables |
| --- | --- |
| Accounts | workspaces, users, connections |
| Sending setup | domains, mailboxes |
| Campaigns | campaigns, sequence_steps |
| Leads | leads, lead_emails |
| Outreach | enrollments, messages, events |
| Safety and limits | suppression, license_state |
| Analytics | experiments, spend_ledger |

Rules that apply to every model:

- Every class sets `__tablename__` explicitly; SQLModel would otherwise derive singular names.
- Every primary key is `UUID` with a Python `uuid4` default.
- Foreign keys are typed `UUID`.
- Optional columns use `X | None = None`.
- Single-column indexes use `index=True`; composite indexes and uniques go in `__table_args__`.
- Composite unique constraints have explicit full names for readability.
- Files are created in dependency order, so referenced tables exist first.

### 9.1 workspace.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, utcnow


class Workspace(TimestampMixin, table=True):
    __tablename__ = "workspaces"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    sender_identity: str | None = None
    postal_address: str | None = None
    footer_text: str | None = None
    timezone: str = "UTC"
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


class User(TimestampMixin, table=True):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_users_workspace_id_email"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, email) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    email: str
    password_hash: str
    role: str = "admin"
    totp_secret: str | None = None
```

### 9.2 connection.py

```python
from uuid import UUID, uuid4

from sqlmodel import Field

from app.models.base import TimestampMixin


class Connection(TimestampMixin, table=True):
    __tablename__ = "connections"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    kind: str  # llm | verifier | apollo | apify | smtp | imap
    encrypted_secret: str  # Fernet-encrypted credential; never returned by the API
    status: str = "unconfigured"
```

### 9.3 domain.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, tz_column


class Domain(TimestampMixin, table=True):
    __tablename__ = "domains"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_domains_workspace_id_name"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, name) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    name: str
    spf_ok: bool = False
    dkim_ok: bool = False
    dmarc_ok: bool = False
    warmup_started_at: datetime | None = Field(default=None, sa_column=tz_column())


class Mailbox(TimestampMixin, table=True):
    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "address", name="uq_mailboxes_workspace_id_address"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (workspace_id, address) constraint below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    domain_id: UUID = Field(foreign_key="domains.id", index=True)
    address: str
    daily_cap: int = 40
    status: str = "warming"  # warming | active | paused
    health_score: float = 100.0
```

### 9.4 campaign.py

```python
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column


class Campaign(TimestampMixin, table=True):
    __tablename__ = "campaigns"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    name: str
    product: dict = Field(default_factory=dict, sa_column=jsonb_column())
    icp: dict = Field(default_factory=dict, sa_column=jsonb_column())
    status: str = "draft"
    compliance_mode: str = "standard"
    require_approval: bool = True


class SequenceStep(TimestampMixin, table=True):
    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "step_no", name="uq_sequence_steps_campaign_id_step_no"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (campaign_id, step_no) constraint below.
    campaign_id: UUID = Field(foreign_key="campaigns.id")
    step_no: int
    delay_days: int = 3
    angle_hint: str | None = None
```

### 9.5 lead.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column, tz_column, utcnow


class Lead(TimestampMixin, table=True):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_workspace_id_company_domain", "workspace_id", "company_domain"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the composite (workspace_id, company_domain) index below.
    workspace_id: UUID = Field(foreign_key="workspaces.id")
    source: str
    company_domain: str | None = None
    company_name: str | None = None
    person_name: str | None = None
    title: str | None = None
    country: str | None = None
    icp_score: float | None = None
    lawful_basis: str | None = None
    collected_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    raw: dict = Field(default_factory=dict, sa_column=jsonb_column())


class LeadEmail(TimestampMixin, table=True):
    __tablename__ = "lead_emails"
    __table_args__ = (
        UniqueConstraint("lead_id", "email", name="uq_lead_emails_lead_id_email"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (lead_id, email) constraint below.
    lead_id: UUID = Field(foreign_key="leads.id")
    email: str = Field(index=True)
    verify_status: str = "unknown"  # valid | risky | invalid | unknown
    verified_at: datetime | None = Field(default=None, sa_column=tz_column())
    role_based: bool = False
```

### 9.6 enrollment.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Text, UniqueConstraint, Column
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column, tz_column, utcnow


class Enrollment(TimestampMixin, table=True):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "lead_id", name="uq_enrollments_campaign_id_lead_id"
        ),
        Index("ix_enrollments_status_next_send_at", "status", "next_send_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Covered by the unique (campaign_id, lead_id) constraint below.
    campaign_id: UUID = Field(foreign_key="campaigns.id")
    lead_id: UUID = Field(foreign_key="leads.id", index=True)
    lead_email_id: UUID = Field(foreign_key="lead_emails.id", index=True)
    # Assigned when the first email is sent and reused for follow-ups.
    mailbox_id: UUID | None = Field(default=None, foreign_key="mailboxes.id", index=True)
    status: str = "new"
    step_no: int = 0
    next_send_at: datetime | None = Field(default=None, sa_column=tz_column())
    variant_id: str | None = None


class Message(TimestampMixin, table=True):
    __tablename__ = "messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    enrollment_id: UUID = Field(foreign_key="enrollments.id", index=True)
    direction: str  # out | in
    message_id: str | None = Field(default=None, index=True)
    in_reply_to: str | None = None
    thread_id: str | None = None
    subject: str
    body: str = Field(sa_column=Column(Text, nullable=False))
    variant_id: str | None = None
    sent_at: datetime | None = Field(default=None, sa_column=tz_column())


class Event(TimestampMixin, table=True):
    __tablename__ = "events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    enrollment_id: UUID = Field(foreign_key="enrollments.id", index=True)
    type: str
    payload: dict = Field(default_factory=dict, sa_column=jsonb_column())
    at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
```

### 9.7 suppression.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlmodel import Field

from app.models.base import TimestampMixin, utcnow


class Suppression(TimestampMixin, table=True):
    __tablename__ = "suppression"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Hashed so the database never stores a plain suppression address.
    email_hash: str = Field(unique=True, index=True)
    domain: str | None = None
    reason: str
    at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
```

### 9.8 analytics.py

```python
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field

from app.models.base import TimestampMixin, jsonb_column


class Experiment(TimestampMixin, table=True):
    __tablename__ = "experiments"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    campaign_id: UUID = Field(foreign_key="campaigns.id", index=True)
    kind: str
    variants: dict = Field(default_factory=dict, sa_column=jsonb_column())
    stats: dict = Field(default_factory=dict, sa_column=jsonb_column())


class SpendLedger(TimestampMixin, table=True):
    __tablename__ = "spend_ledger"
    __table_args__ = (Index("ix_spend_ledger_day_kind", "day", "kind"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    day: date
    kind: str  # llm | verify | source
    units: int = 0
    est_usd: float = 0.0
```

### 9.9 license.py

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TimestampMixin, tz_column


class LicenseState(TimestampMixin, table=True):
    __tablename__ = "license_state"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    token: str = Field(sa_column=Column(Text, nullable=False))
    valid_until: datetime | None = Field(default=None, sa_column=tz_column())
    last_checked_at: datetime | None = Field(default=None, sa_column=tz_column())
```

### 9.10 Import every model

Alembic and the tests only see tables whose classes have been imported. Create `backend/app/models/__init__.py`:

```python
from app.models.base import apply_naming_convention

# The naming convention must be set before any table class below is imported,
# because table names are generated when the class is defined.
apply_naming_convention()

# Import every model so SQLModel.metadata knows about all tables.
# Alembic and the tests rely on this.
from app.models.workspace import User, Workspace  # noqa: E402, F401
from app.models.connection import Connection  # noqa: E402, F401
from app.models.domain import Domain, Mailbox  # noqa: E402, F401
from app.models.campaign import Campaign, SequenceStep  # noqa: E402, F401
from app.models.lead import Lead, LeadEmail  # noqa: E402, F401
from app.models.enrollment import Enrollment, Event, Message  # noqa: E402, F401
from app.models.suppression import Suppression  # noqa: E402, F401
from app.models.analytics import Experiment, SpendLedger  # noqa: E402, F401
from app.models.license import LicenseState  # noqa: E402, F401

__all__ = [
    "Campaign",
    "Connection",
    "Domain",
    "Enrollment",
    "Event",
    "Experiment",
    "Lead",
    "LeadEmail",
    "LicenseState",
    "Mailbox",
    "Message",
    "SequenceStep",
    "SpendLedger",
    "Suppression",
    "User",
    "Workspace",
]
```

If a model is missing here, its table silently disappears from the migration.

## 10. Why Every Table and Every Column Exists

Before moving on, let us slow down and understand the schema. This section is the most important one in the module: a table you cannot explain is a table you will misuse later.

A quick vocabulary reminder:

- A **table** is a drawer in a filing cabinet for one kind of thing (leads, emails, users).
- A **column** (field) is a labeled slot that every record in that drawer has.
- A **row** is one record inside the table.

People sometimes say "row" when they mean a field; below, every **column** is explained.

Two design ideas drive the whole schema:

1. **Store each fact once.** The workspace mailing address is stored in `workspaces`, not copied into every lead. If it changes, it changes in one place.
2. **Give different kinds of things different tables.** A lead is a person/company. An enrollment is that person's journey through one campaign. Two campaigns can contact the same lead independently without overwriting each other.

Every table also gets `id` and `created_at`:

- `id` — a UUID so records can be created anywhere without asking the database for the next number, and IDs are not guessable in URLs.
- `created_at` — an audit stamp: when did this record appear?

### 10.1 workspaces

**Purpose:** one row per client deployment. Holds the identity and legal footer used in every email.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity; every tenant table points here. |
| `name` | Workspace label | Shown in the dashboard and support screens. |
| `sender_identity` | Who the email is from | Anti-spam laws require an honest sender; also used in the footer. |
| `postal_address` | Business mailing address | Required in commercial email footers (CAN-SPAM and similar). Sending is blocked until filled. |
| `footer_text` | Optional extra footer line | Company description or custom wording; the code, not the AI, adds the final footer. |
| `timezone` | Client's local timezone | Send windows and daily reports follow the client's clock; timestamps stay UTC. |
| `created_at` | Creation time | Audit. |
| `updated_at` | Last settings change | Helps support understand when identity or footer changed. |

### 10.2 users

**Purpose:** people allowed to log into the dashboard.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Keeps logins scoped to one client deployment. |
| `email` | Login name | Unique per workspace. |
| `password_hash` | bcrypt/argon2 hash | We never store the password itself; only the verifier hash. |
| `role` | admin / member | Controls who may change mailboxes, licenses, and compliance settings. |
| `totp_secret` | Optional 2FA secret | Extra protection for admin accounts. |
| `created_at` | Creation time | Audit. |

The unique constraint `(workspace_id, email)` prevents two logins with the same email in one workspace, while still allowing the same email in a different workspace later.

### 10.3 connections

**Purpose:** the client-owned credentials for outside services (LLM, verifier, Apollo, Apify, SMTP, IMAP).

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Credentials never cross clients. |
| `kind` | llm / verifier / apollo / apify / smtp / imap | One table serves every provider type. |
| `encrypted_secret` | Fernet-encrypted credential | Secrets are never stored or returned in plain text. |
| `status` | unconfigured / ok / failed | Lets the dashboard show a broken connection instead of silently failing jobs. |
| `created_at` | Creation time | Audit. |

Why a separate table: secrets live in exactly one place, can be rotated independently, and are easy to redact in support bundles.

### 10.4 domains

**Purpose:** the sending domains and their DNS health.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Tenant isolation. |
| `name` | Domain name | Must be unique per workspace. |
| `spf_ok` | SPF check passed | Deliverability guard; sending is blocked until green. |
| `dkim_ok` | DKIM check passed | Cryptographic signature; mailbox providers require it. |
| `dmarc_ok` | DMARC check passed | Policy record; required for good deliverability. |
| `warmup_started_at` | When warm-up began | The ramp schedule depends on the start date. |
| `created_at` | Creation time | Audit. |

Each DNS check is a separate boolean so the setup wizard can show exactly which record is still missing.

### 10.5 mailboxes

**Purpose:** individual email accounts used to send.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Tenant isolation. |
| `domain_id` | Parent sending domain | Groups mailboxes under a domain; DNS status is checked there. |
| `address` | Full email address | The actual From address. |
| `daily_cap` | Max sends per day | Protects reputation; about 30-50 cold emails per mailbox per day. |
| `status` | warming / active / paused | The send loop only picks `active` mailboxes. |
| `health_score` | Bounce/complaint health | Auto-pause when it drops; keeps the rest of the account safe. |
| `created_at` | Creation time | Audit. |

Unique `(workspace_id, address)` prevents adding the same mailbox twice.

### 10.6 campaigns

**Purpose:** one outreach project: a product, an audience, and the rules for contacting it.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Tenant isolation. |
| `name` | Campaign label | Shown in the UI. |
| `product` | JSONB description | What the client sells: features, links, tone. Used by drafting and by the critic. |
| `icp` | JSONB ideal-customer profile | Roles, industries, company size, countries. Used to score leads. |
| `status` | draft / active / paused / archived | Controls whether sourcing and sending are allowed. |
| `compliance_mode` | standard / strict | Region rules; strict blocks Germany/Canada without a recorded lawful basis. |
| `require_approval` | true/false | Human approval of drafts; mandatory for the first 50 emails. |
| `created_at` | Creation time | Audit. |

`product` and `icp` are JSONB because their shape keeps evolving; requiring a migration for every new field would slow the product down.

### 10.7 sequence_steps

**Purpose:** the follow-up plan of a campaign.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `campaign_id` | Parent campaign | Steps belong to exactly one campaign. |
| `step_no` | 1, 2, 3... | Order of the sequence. |
| `delay_days` | Wait before this step | Spacing; avoids looking like a bulk blast. |
| `angle_hint` | What angle to use | Guides the AI without dictating exact wording. |
| `created_at` | Creation time | Audit. |

Unique `(campaign_id, step_no)` guarantees there are not two "step 2" rows for the same campaign.

### 10.8 leads

**Purpose:** a person and company we might contact, plus the compliance record of where the data came from.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `workspace_id` | Owning workspace | Tenant isolation. |
| `source` | csv / website / apollo / apify | Provenance: where the record came from. |
| `company_domain` | Company website domain | Deduplication and personalization research. |
| `company_name` | Company name | Display and personalization. |
| `person_name` | Contact name | Personalization. |
| `title` | Job title | ICP scoring and relevance. |
| `country` | Country | The recipient's country decides which email law applies. |
| `icp_score` | Computed fit score | Queue ordering; spend effort on the best matches. |
| `lawful_basis` | Why contact is allowed | GDPR-style record keeping; proves relevance/consent basis. |
| `collected_at` | When data was obtained | Audit and data-age rules. |
| `raw` | Original JSONB payload | Provenance/debugging if a vendor record is questioned. |
| `created_at` | Creation time | Audit. |

### 10.9 lead_emails

**Purpose:** every email address belonging to a lead, with its verification state.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `lead_id` | Parent lead | A lead can have several addresses. |
| `email` | The address | The actual destination. |
| `verify_status` | valid / risky / invalid / unknown | Only `valid` sends; `risky` at a capped share; `invalid` never. |
| `verified_at` | When verification ran | Results older than 30 days are re-verified. |
| `role_based` | info@, sales@, etc. | Quality/risk signal, separate from syntax validity. |
| `created_at` | Creation time | Audit. |

Why not put the email on `leads`? Because verification and suppression apply per address, and an enrollment must reference exactly the address being used. Unique `(lead_id, email)` prevents duplicates.

### 10.10 enrollments

**Purpose:** one lead's journey through one campaign. This is the row the state machine moves.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `campaign_id` | Campaign | Which outreach project. |
| `lead_id` | Lead | Who is being contacted. |
| `lead_email_id` | The specific address | Verification and suppression apply to this address. |
| `mailbox_id` | Sticky sending mailbox | Assigned at the first send, **null before that**; follow-ups must come from the same mailbox and thread. |
| `status` | new / scored / verified / drafted / queued / step1_sent / ... | The state machine's current position; only `state_machine.py` may change it. |
| `step_no` | Progress in the sequence | Knows which step is next. |
| `next_send_at` | When to act next | The scheduler's clock; `null` means nothing is due. |
| `variant_id` | A/B variant | Which subject/opener/CTA was used. |
| `created_at` | Creation time | Audit. |

Unique `(campaign_id, lead_id)` prevents enrolling the same lead twice in the same campaign. The same lead can still be in two different campaigns, which is why status does not live on `leads`.

### 10.11 messages

**Purpose:** every email sent and received, so threads and replies can be matched.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `enrollment_id` | Parent enrollment | Every message belongs to one journey. |
| `direction` | out / in | Tells sent mail from replies. |
| `message_id` | SMTP Message-ID | The key for matching inbound replies. |
| `in_reply_to` | Header from the reply | Links a reply to the original send. |
| `thread_id` | Conversation grouping | Keeps follow-ups in the same thread. |
| `subject` | Subject line | Display and thread checks. |
| `body` | Full body (Text) | Needed for classification; never logged or exported. |
| `variant_id` | A/B variant | Attribution for experiments. |
| `sent_at` | When it was sent | Timeline and reply-time metrics. |
| `created_at` | Creation time | Audit. |

### 10.12 events

**Purpose:** an audit timeline of everything that happened to an enrollment.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `enrollment_id` | Parent enrollment | Timeline scope. |
| `type` | e.g. `status:queued`, `bounce`, `reply` | Human-readable event kind. |
| `payload` | JSONB details/reason | Extra context without a column for every event type. |
| `at` | When it happened | Ordering the timeline. |
| `created_at` | Creation time | Audit. |

Events are separate from messages because most events are not emails: status changes, suppressions, bounces, pauses.

### 10.13 suppression

**Purpose:** the permanent "never contact again" list, checked before every send.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `email_hash` | SHA-256 of the normalized address | Privacy: the table never stores a plain address. Unique: one row per person. |
| `domain` | Optional domain | Supports domain-wide suppression. |
| `reason` | unsubscribe / bounce / complaint / manual / forget | Explains why the person is blocked. |
| `at` | When suppression happened | Audit and legal proof. |
| `created_at` | Creation time | Audit. |

This table must keep working even if the license expires. Compliance paths are never disabled.

### 10.14 experiments

**Purpose:** A/B test definitions and results per campaign.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `campaign_id` | Parent campaign | Tests belong to a campaign. |
| `kind` | subject / opener / cta | What is being tested. |
| `variants` | JSONB definitions | Variant text/shape can change without migrations. |
| `stats` | JSONB counters/results | Accumulating statistics without a new schema per metric. |
| `created_at` | Creation time | Audit. |

### 10.15 spend_ledger

**Purpose:** what the client is spending with vendors (the client pays those vendors directly).

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `day` | Calendar day | Daily caps aggregate per day. |
| `kind` | llm / verify / source | Separate budgets per vendor category. |
| `units` | Tokens, verifications, credits | Usage quantity. |
| `est_usd` | Estimated cost | Cap checks and dashboard reporting. |
| `created_at` | Creation time | Audit. |

### 10.16 license_state

**Purpose:** a cached copy of the signed license so the app can validate offline.

| Column | What it stores | Why we need it |
| --- | --- | --- |
| `id` | UUID | Identity. |
| `token` | Signed license token (Text) | Long signed string; verified against an embedded public key. |
| `valid_until` | Expiry from the token | Soft enforcement and the grace period. |
| `last_checked_at` | Last daily validation | Health and support visibility. |
| `created_at` | Creation time | Audit. |

## 11. Why Every Index Exists

An index is like the index at the back of a book: instead of reading every page, the database jumps to the matching rows. Without an index, Postgres performs a full table scan.

Indexes are not free:

- They take disk space.
- Every insert, update, and delete must also update the index.

So we add indexes only where a real query needs them. Two useful facts:

1. **A unique constraint is backed by an index.** Uniqueness is enforced by an index, and that same index speeds up lookups. That is why `users` has no separate `workspace_id` index.
2. **Postgres does not index foreign keys automatically.** We add an index on a foreign key only when we look rows up by it.

### 11.1 Unique constraints (which also act as indexes)

| Constraint | Table / columns | Why it exists |
| --- | --- | --- |
| `uq_users_workspace_id_email` | users(`workspace_id`, `email`) | One login per email per workspace; also makes login lookups fast. |
| `uq_domains_workspace_id_name` | domains(`workspace_id`, `name`) | No duplicate domain; the leftmost `workspace_id` also serves workspace listing. |
| `uq_mailboxes_workspace_id_address` | mailboxes(`workspace_id`, `address`) | No duplicate mailbox; supports workspace listing via the leftmost column. |
| `uq_sequence_steps_campaign_id_step_no` | sequence_steps(`campaign_id`, `step_no`) | One row per step number; loads a campaign's steps in order. |
| `uq_lead_emails_lead_id_email` | lead_emails(`lead_id`, `email`) | No duplicate address per lead; listing a lead's addresses is fast. |
| `uq_enrollments_campaign_id_lead_id` | enrollments(`campaign_id`, `lead_id`) | Prevents enrolling the same lead twice in a campaign (double emailing). |

**Leftmost-prefix rule:** a composite index on `(a, b)` can also answer queries that filter only on `a`. That is why `users`, `domains`, `mailboxes`, `sequence_steps`, and `lead_emails` do not need a second single-column index for their first column.

### 11.2 Explicit indexes

| Index | Table / columns | Query it serves |
| --- | --- | --- |
| `ix_suppression_email_hash` (unique) | suppression(`email_hash`) | The hottest check in the system: "is this person suppressed?" before every send. Unique also prevents duplicate suppressions. |
| `ix_enrollments_status_next_send_at` | enrollments(`status`, `next_send_at`) | The send engine's work queue: active statuses with a due time, ordered by time. Without it, every minute scans all enrollments. |
| `ix_messages_message_id` | messages(`message_id`) | Inbox matching: find the original send when a reply arrives with `In-Reply-To`/`References`. |
| `ix_leads_workspace_id_company_domain` | leads(`workspace_id`, `company_domain`) | Deduplicate incoming leads by company domain inside a workspace; also covers workspace-only filters (leftmost prefix). |
| `ix_lead_emails_email` | lead_emails(`email`) | Find an address across all leads for dedupe, verification, and suppression checks. |
| `ix_campaigns_workspace_id` | campaigns(`workspace_id`) | List a workspace's campaigns. |
| `ix_connections_workspace_id` | connections(`workspace_id`) | Load a workspace's configured providers. |
| `ix_mailboxes_domain_id` | mailboxes(`domain_id`) | List mailboxes per domain and show DNS/warm-up status. |
| `ix_experiments_campaign_id` | experiments(`campaign_id`) | Load a campaign's A/B tests. |
| `ix_enrollments_lead_id` | enrollments(`lead_id`) | Lead history: what happened with this person across campaigns. |
| `ix_enrollments_lead_email_id` | enrollments(`lead_email_id`) | Find journeys using a specific address when it bounces or unsubscribes. |
| `ix_enrollments_mailbox_id` | enrollments(`mailbox_id`) | Mailbox health/pause: which journeys use this mailbox. |
| `ix_events_enrollment_id` | events(`enrollment_id`) | Render one enrollment's timeline. |
| `ix_messages_enrollment_id` | messages(`enrollment_id`) | Load the conversation for one enrollment. |
| `ix_spend_ledger_day_kind` | spend_ledger(`day`, `kind`) | Daily cap checks and month-to-date reports: sum usage for one day and category. |

### 11.3 Indexes we intentionally did not create

- **No single-column `workspace_id` index** on users, domains, mailboxes, sequence_steps, lead_emails, and enrollments: their composite unique/index already starts with that column.
- **No index on status alone:** `status` has few distinct values (low cardinality), so a plain status index rarely helps. The scheduler needs the composite with `next_send_at`.
- **No index on booleans** such as `spf_ok` or `role_based`: two possible values do not narrow a scan enough to justify the write cost.
- **No index on `body`/`subject`:** there is no search feature in v1. A future search feature can add the right index then.
- **No index on every foreign key:** only the foreign keys we actually query by get one.

## 12. Create the Async Session and Test the Connection

Create `backend/app/core/db.py`:

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# One engine for the whole app. It connects lazily on first use.
engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)

# expire_on_commit=False keeps objects usable after commit, which is handy
# inside background jobs.
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that gives each request its own session."""
    async with Session() as session:
        yield session
```

Why these options:

- `pool_pre_ping=True` checks that a pooled connection is still alive. Cloud poolers close idle connections; this avoids random errors after a quiet period.
- `expire_on_commit=False` keeps objects readable after `commit()`. In async code, touching an expired object triggers a reload that can fail.
- `get_session()` is a FastAPI dependency: one session per request, closed afterward.

Now test the first real connection. Create a temporary file `backend/check_db.py`:

```python
import asyncio

from sqlalchemy import text

from app.core.db import engine


async def main():
    async with engine.connect() as conn:
        print((await conn.execute(text("select version()"))).scalar())
    await engine.dispose()


asyncio.run(main())
```

Run it from `backend`:

```
python check_db.py
```

If you see a PostgreSQL version string, the connection works. Delete `check_db.py` afterward. If it fails, see the troubleshooting table in Section 18.

## 13. Set Up Alembic

Initialize Alembic with the async template (run inside `backend`):

```
venv\Scripts\alembic.exe init -t async alembic
```

### 13.1 Edit alembic.ini

Open `alembic.ini` and remove the line starting with `sqlalchemy.url`. We never hardcode a URL here, so no secret can end up in this file. `env.py` decides the URL.

### 13.2 Replace env.py

Replace the contents of `alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

# Importing app.models registers every table on SQLModel.metadata and applies
# the constraint naming convention.
import app.models  # noqa: F401
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_database_url() -> str:
    # Tests inject a URL with config.set_main_option(...). Otherwise we use
    # the value from backend/.env.
    return config.get_main_option("sqlalchemy.url") or settings.async_database_url


target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live database connection (emits SQL)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Put the URL in the section dict instead of the ConfigParser, so a "%"
    # inside a URL-encoded password is never interpreted as interpolation.
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The important lines:

- `get_database_url()` prefers a URL injected on the Alembic config (the migration test does this), otherwise it uses `settings.async_database_url` from `.env`.
- `target_metadata = SQLModel.metadata` tells Alembic which tables our models define.
- `compare_type=True` makes future migrations notice column type changes.
- The URL is placed in the section dictionary for the engine. If it went through `ConfigParser.set`, a `%` in an encoded password (for example `%40` for `@`) would be treated as interpolation syntax.
- `NullPool` opens a fresh connection for the migration and closes it; migrations are not a hot path.

We do not edit `script.py.mako` in this implementation. Alembic would render SQLModel's `AutoString` type into a generated migration, so the committed migration uses plain `sa.String()` instead (we normalize it during review). If you generate a new migration later, either import `sqlmodel` in that file or replace `sqlmodel.sql.sqltypes.AutoString()` with `sa.String()`.

## 14. Generate and Review the Migration

The committed migration is `backend/alembic/versions/0001_initial_schema.py` with revision id `0001`.

How it was produced: no database was reachable during implementation, so the file was rendered from `SQLModel.metadata` with Alembic's autogenerate renderer against an empty temporary SQLite database, then normalized and reviewed. This is a known, honest workflow:

- Autogenerate needs a live database to compare against.
- Rendering against an empty database produces "create everything" operations.
- The target dialect only matters when the SQL runs; the migration file itself is dialect-neutral Python.

Once `.env` exists you can preview the real Postgres SQL without applying it:

```
venv\Scripts\alembic.exe upgrade head --sql
```

This must exit with code 0 and show `TIMESTAMP WITH TIME ZONE`, `UUID`, `JSONB`, indexes, and named constraints.

### 14.1 The review checklist

Read the generated migration line by line. Autogenerate is a draft, not a final answer. Check:

- Exactly 16 `op.create_table(...)` calls in `upgrade()`.
- Primary keys use `sa.Uuid()`.
- Every timestamp uses `sa.DateTime(timezone=True)`.
- Every JSONB column is `nullable=False` with `server_default=sa.text("'{}'::jsonb")`.
- All composite uniques exist with explicit names:
  - `uq_users_workspace_id_email`
  - `uq_domains_workspace_id_name`
  - `uq_mailboxes_workspace_id_address`
  - `uq_sequence_steps_campaign_id_step_no`
  - `uq_lead_emails_lead_id_email`
  - `uq_enrollments_campaign_id_lead_id`
- The required indexes exist:
  - `ix_enrollments_status_next_send_at`
  - `ix_leads_workspace_id_company_domain`
  - `ix_messages_message_id`
  - `ix_suppression_email_hash` (unique)
  - `ix_spend_ledger_day_kind`
- `downgrade()` drops every index and table in reverse dependency order.
- No `sqlmodel.sql.sqltypes.AutoString()` remains; use `sa.String()`.

A typical JSONB column looks like this:

```python
sa.Column(
    "product",
    postgresql.JSONB(astext_type=sa.Text()),
    server_default=sa.text("'{}'::jsonb"),
    nullable=False,
),
```

If you change a model later, generate a new migration with a reachable database:

```
venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
```

then review it again before applying.

## 15. Apply, Reverse, and Apply Again

With `.env` filled in, run against the empty development database:

```
venv\Scripts\alembic.exe upgrade head
```

Open the Supabase dashboard, then Table Editor. You should see 16 application tables plus `alembic_version`, which Alembic manages itself (17 in total).

Reverse it:

```
venv\Scripts\alembic.exe downgrade base
```

The 16 application tables disappear. Only `alembic_version` remains.

Apply once more:

```
venv\Scripts\alembic.exe upgrade head
```

If all three commands succeed, the migration is repeatable and reversible.

## 16. Write the Tests

Create `backend/pytest.ini`:

```
[pytest]
testpaths = tests
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
markers =
    integration: needs a real database (TEST_DATABASE_URL); never runs by default
```

### 16.1 Models test (no database needed)

Create `tests/test_models.py`:

```python
from sqlalchemy import UniqueConstraint, Uuid
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table)

EXPECTED_TABLES = {
    "campaigns",
    "connections",
    "domains",
    "enrollments",
    "events",
    "experiments",
    "lead_emails",
    "leads",
    "license_state",
    "mailboxes",
    "messages",
    "sequence_steps",
    "spend_ledger",
    "suppression",
    "users",
    "workspaces",
}


def test_all_tables_exist():
    assert set(SQLModel.metadata.tables) == EXPECTED_TABLES


def test_primary_keys_are_uuid():
    for table_name in EXPECTED_TABLES:
        table = SQLModel.metadata.tables[table_name]
        assert isinstance(table.c.id.type, Uuid), table_name


def test_required_indexes_exist():
    def index_names(table_name: str) -> set[str]:
        table = SQLModel.metadata.tables[table_name]
        return {index.name for index in table.indexes}

    assert "ix_enrollments_status_next_send_at" in index_names("enrollments")
    assert "ix_leads_workspace_id_company_domain" in index_names("leads")
    assert "ix_spend_ledger_day_kind" in index_names("spend_ledger")
    assert "ix_messages_message_id" in index_names("messages")


def test_suppression_email_hash_is_unique():
    table = SQLModel.metadata.tables["suppression"]
    assert table.c.email_hash.unique is True
    assert any(
        index.unique and [column.name for column in index.columns] == ["email_hash"]
        for index in table.indexes
    )


def test_composite_unique_constraints():
    def unique_names(table_name: str) -> set[str]:
        table = SQLModel.metadata.tables[table_name]
        return {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert "uq_enrollments_campaign_id_lead_id" in unique_names("enrollments")
    assert "uq_users_workspace_id_email" in unique_names("users")
    assert "uq_lead_emails_lead_id_email" in unique_names("lead_emails")
    assert "uq_sequence_steps_campaign_id_step_no" in unique_names("sequence_steps")


def test_enrollment_mailbox_is_optional():
    # The mailbox is assigned when the first email is sent, not at enrollment.
    assert SQLModel.metadata.tables["enrollments"].c.mailbox_id.nullable is True
```

### 16.2 URL normalization test

Create `tests/test_config.py`:

```python
from app.core.config import normalize_database_url


def test_supabase_url_becomes_asyncpg():
    url = (
        "postgresql://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/"
        "postgres?sslmode=require"
    )

    assert normalize_database_url(url) == (
        "postgresql+asyncpg://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/"
        "postgres?ssl=require"
    )


def test_unsupported_parameters_are_removed():
    url = (
        "postgresql://user:pass@host:5432/db"
        "?sslmode=require&channel_binding=require&pgbouncer=true"
    )

    assert normalize_database_url(url) == (
        "postgresql+asyncpg://user:pass@host:5432/db?ssl=require"
    )


def test_plain_and_already_asyncpg_urls():
    assert normalize_database_url("postgres://u:p@h/db") == (
        "postgresql+asyncpg://u:p@h/db"
    )

    already = "postgresql+asyncpg://u:p@h/db?ssl=require"
    assert normalize_database_url(already) == already
```

### 16.3 Migration integration test

This test runs the real migration against the separate test project. Create `tests/test_migrations.py`:

```python
import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import normalize_database_url, settings
from tests.test_models import EXPECTED_TABLES

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[1]


def get_test_database_url() -> str:
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping migration test")

    test_url = normalize_database_url(settings.test_database_url)
    dev_url = settings.async_database_url

    # Safety check: never run downgrade/base against the development database.
    # Supabase pooler hosts are shared by region, so compare host, username
    # (it contains the project ref) and database name together.
    dev_parts = urlsplit(dev_url)
    test_parts = urlsplit(test_url)
    dev_key = (dev_parts.hostname, dev_parts.username, dev_parts.path)
    test_key = (test_parts.hostname, test_parts.username, test_parts.path)
    if dev_key == test_key:
        pytest.fail(
            "TEST_DATABASE_URL must point to a separate Supabase project, "
            "not the same project as DATABASE_URL"
        )

    return test_url


@pytest.fixture(scope="module")
def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # Alembic's config parser treats "%" specially, and URL-encoded passwords
    # contain it (for example %40 for "@"). Escape and let the parser restore it.
    config.set_main_option(
        "sqlalchemy.url", get_test_database_url().replace("%", "%%")
    )
    return config


async def table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
    finally:
        await engine.dispose()
    return set(names)


def test_upgrade_downgrade_upgrade(alembic_config: Config) -> None:
    database_url = alembic_config.get_main_option("sqlalchemy.url")

    command.upgrade(alembic_config, "head")
    tables = asyncio.run(table_names(database_url))
    assert EXPECTED_TABLES <= tables
    assert "alembic_version" in tables

    command.downgrade(alembic_config, "base")
    tables = asyncio.run(table_names(database_url))
    assert not (EXPECTED_TABLES & tables)

    command.upgrade(alembic_config, "head")
    tables = asyncio.run(table_names(database_url))
    assert EXPECTED_TABLES <= tables
```

Important choices:

- The safety guard compares hostname, username, and database name. Supabase projects in the same region share a pooler hostname, so hostname alone would wrongly block a valid test project; the username contains the project reference, which distinguishes them.
- The test is a normal `def`, not `async def`. Our `env.py` calls `asyncio.run()` internally, which cannot run inside an already running event loop.
- `%` is escaped as `%%` before `set_main_option` because Alembic's config parser treats `%` as interpolation; URL-encoded passwords commonly contain `%`.
- The URL is read back with `get_main_option`, which restores the single `%`.

Run everything:

```
venv\Scripts\python.exe -m pytest -v
```

Fast tests only, without any database:

```
venv\Scripts\python.exe -m pytest -m "not integration" -v
```

Current expected result without `.env`: **9 passed, 1 skipped**. The skipped test is the migration test.

## 17. Final Checks and Progress Notes

Confirm the app still starts:

```
fastapi dev app/main.py
```

Open `http://127.0.0.1:8000/health`. It should return `ok`. No database check was added to `/health` in this module.

Then update `PROGRESS.md` with:

- Module 1 status (implemented; live migration pending or done)
- Test result
- Any Supabase issues
- Next module: the state machine

## 18. Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `Invalid requirement: '-'` | Space after `-r` in pip command | Run `pip install -r requirements.txt` (no space). |
| Connection fails or network unreachable | Direct host used (IPv6-only by default) | Use the Session pooler string, port 5432. |
| Prepared statement errors or DDL failures | Transaction pooler (port 6543) | Switch to port 5432. |
| `unexpected keyword argument 'sslmode'` | URL was not normalized | Load it through `settings.async_database_url` or `normalize_database_url()`. |
| `Invalid interpolation syntax` in Alembic | A `%` in the password reached `ConfigParser` | Inject the URL through the section dictionary (as `env.py` does) or escape `%` as `%%`. |
| Index or unique missing from migration | Autogenerate missed it | Add it by hand and re-check Section 14.1. |
| Duplicate index name error | Naming convention applied too late | Keep `apply_naming_convention()` at the top of `models/__init__.py`, before model imports. |
| `asyncio.run() cannot be called from a running event loop` | Async migration test | Keep the migration test as a normal `def`. |
| Migration test refuses to run | Test URL points at the dev project | Use the Project B Session pooler string. |
| Install or connect error on Python 3.14 | Package support lag | Use a Python version that asyncpg supports. |

## 19. Acceptance Checklist

Code and offline checks already pass in this implementation:

- [x] 16 application tables defined in SQLModel metadata.
- [x] UUID primary keys, UTC timestamps, JSONB columns, composite uniques, required indexes.
- [x] Alembic renders valid Postgres DDL (`alembic upgrade head --sql`, exit 0).
- [x] `pytest`: 9 passed, 1 skipped (migration test waits for `TEST_DATABASE_URL`).
- [x] `fastapi dev app/main.py` starts and `/health` returns `ok`.
- [x] `PROGRESS.md` updated.

Still requires the real Supabase URLs in `backend/.env`:

- [ ] `alembic upgrade head` applies cleanly to the empty Supabase dev database.
- [ ] 16 application tables plus `alembic_version` exist.
- [ ] `alembic downgrade base` removes all application tables.
- [ ] `alembic upgrade head` succeeds again.
- [ ] `pytest` passes, including the migration test on the separate test project.

## 20. Things to Remember

1. Alembic autogenerate is a draft. Always read the migration line by line.
2. Never run migrations through the transaction pooler (port 6543).
3. Keep real credentials only in `backend/.env`, and make sure it is gitignored before the first commit.
4. Never point the migration test at the development database.
5. An index is a trade: faster reads, slower writes. Add one only for a real query.
6. A unique constraint already creates an index; do not add a second one for the same column.
7. Known issue for later: `passlib 1.7.4` and `bcrypt 5` are incompatible. Fix it in Module 7 (auth), not now.

## Conclusion

We built the data layer of the lead generation system: 16 SQLModel tables with UUID keys, timezone-aware timestamps, JSONB columns, named constraints, and purpose-built indexes; an async session for FastAPI; and an Alembic migration that creates and removes the whole schema.

We also explained, table by table and column by column, why each piece exists, because a schema you understand is a schema you can safely change. With the tests in place, every future schema change can be checked automatically.

In Module 2 we build the state machine on top of this foundation.

*Part of the Asadullah AI Lead Generation Agent series.*
