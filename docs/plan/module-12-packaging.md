# Module 12 Plan - Docker Packaging and Deployment

Status: planned (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 4-7, 9,
21, and 22 (module 12).
Acceptance test from the design: **a fresh VPS install completes in under
30 minutes, and update plus rollback complete successfully**.

## Goal

Package LeadGen as one dedicated Docker deployment per client:

1. Build the FastAPI API and ARQ worker from one versioned application image.
2. Add Docker Compose for Caddy, the static web directory, API, worker,
   Postgres, and Redis.
3. Add a simple install script that validates the VPS and creates the secrets
   and environment file.
4. Add update and rollback behavior for image upgrades.
5. Add encrypted-at-rest database backup handling and restore instructions.
6. Add a redacted support-bundle script that never exports secrets or email bodies.
7. Add focused tests that validate configuration and script behavior without
   contacting real providers or servers.

## Out of scope

- React dashboard and setup wizard screens; Module 13 owns the frontend.
- Campaign optimizer and weekly reports; Module 14 owns optimization.
- Source, verifier, mail, license, and state-machine behavior; Modules 2-11
  already own these implementations.
- A public SaaS control plane or shared multi-client hosting.
- Automatic updates. Updates remain explicit through `update.sh`.
- Off-box backup provider integrations beyond optional local copy or a
  clearly documented command seam.
- Real VPS, DNS, SMTP, IMAP, Postgres, Redis, or Caddy testing. Tests use
  Fake providers and local shell/config checks.

## Decisions

| Question | Decision |
|---|---|
| Packaging | Use Docker Compose on one VPS with internal Docker networking. |
| Application image | Build once for both `api` and `worker`; use commands to select the process. |
| Versioning | `VERSION` and `REGISTRY_IMAGE` are required deployment values. |
| Public TLS | Caddy listens on ports 80 and 443 and serves `/api` to FastAPI plus `/` to static web files. |
| Database | Postgres 16 only, with a named Docker volume. Do not expose port 5432 publicly. |
| Redis | Redis 7 with append-only persistence and a named Docker volume. Do not expose Redis publicly. |
| Secrets | Generate `SECRET_KEY`, `FERNET_KEY`, and `DB_PASSWORD`; store only in the deployment `.env`. |
| Client credentials | Continue to resolve client-owned credentials through existing encrypted connection settings. |
| Install result | `.env` plus running containers plus `/health` success. |
| Migration startup | API runs `alembic upgrade head` before starting Uvicorn. |
| Health check | `/health` remains a liveness check; Docker health is implemented without external network calls. |
| Updates | Pull the requested version, migrate, health-check, then keep or roll back to the recorded previous version. |
| Rollback | If migration or health checks fail, restore the previous image tag and restart. Database rollback is not automatic. |
| Backups | Nightly `pg_dump`, 7 daily and 4 weekly local copies, with retention cleanup. |
| Backup secrets | Never copy `.env`, license tokens, API keys, or email bodies into support bundles or backups. |
| Support bundle | Export only version, sanitized configuration, health summary, timestamps, and recent redacted logs. |
| Auto-update | None. The dashboard can show an update available status only after Module 13. |
| Kill switch | Preserve `SENDING_ENABLED=false` behavior and do not package a way to bypass compliance. |

## Deliverables

```text
backend/
  Dockerfile                  # NEW: build API and worker image
  .dockerignore               # NEW
deploy/
  docker-compose.yml          # NEW
  Caddyfile                   # NEW
  .env.example                # NEW
  install.sh                  # NEW
  update.sh                   # NEW
  backup.sh                   # NEW
  restore.sh                  # NEW
  support-bundle.sh           # NEW
docs/
  plan/module-12-packaging.md
  install-guide.md            # NEW
  runbook.md                  # NEW
  backup-restore.md           # NEW
tests/
  test_packaging.py           # NEW
PROGRESS.md                   # UPDATE after implementation
README.md                     # UPDATE after implementation
```

The plan may also add a no-network health script or CI command, but it must not
introduce a new application pattern or dependency.

## Docker image

The image should:

- use a pinned Python 3.14 or project-approved stable runtime base;
- copy only required backend application and package files;
- install packages from `backend/requirements.txt`;
- run as a non-root user;
- expose no SMTP, IMAP, database, or Redis credentials;
- support:

```text
api:
  alembic upgrade head
  uvicorn app.main:app --host 0.0.0.0 --port 8000

worker:
  arq app.workers.arq_settings.WorkerSettings
```

Do not bake a `.env`, license key, database password, or client-owned credential
into the image.

## Compose services

### Caddy

- maps host ports 80 and 443;
- routes `/api/*` to the API while stripping or preserving `/api` exactly according
  to FastAPI router configuration;
- serves static files from `web_dist`;
- persists automatic certificate data in a named volume.

The initial Module 12 build may use a placeholder static readiness page. Module
13 replaces it with the React build. Do not silently expose API secrets through
the static web directory.

### API

- starts from the versioned application image;
- runs migrations once before Uvicorn;
- receives variables only from `.env`;
- has a Docker health check for `/health`;
- depends on Postgres and Redis.

### Worker

- starts from the same image;
- runs ARQ jobs;
- depends on Postgres and Redis;
- never starts as a public HTTP service.

### Postgres

- uses `postgres:16`;
- creates the LeadGen database from `DB_PASSWORD`;
- stores data in `pgdata`;
- is reachable only from the Compose network.

### Redis

- uses `redis:7`;
- enables append-only persistence;
- stores data in `redisdata`;
- is reachable only from the Compose network.

## Environment file

Keep `deploy/.env.example` simple and complete. Include only:

- `PUBLIC_URL`
- `VERSION`
- `REGISTRY_IMAGE`
- `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` only when a private registry needs them
- `DATABASE_URL` or generated `DB_PASSWORD`
- `REDIS_URL`
- `SECRET_KEY`
- `FERNET_KEY`
- `LICENSE_PUBLIC_KEY_PEM`
- `BRAND_NAME`
- `BRAND_LOGO_URL`
- existing sending, LLM, verifier, and spend-cap variables

No real key, token, password, customer data, or license in `.env.example`.

## Install flow

`install.sh` should be a beginner-readable script that performs:

1. OS, Docker, and Compose preflight checks.
2. Port 80 and 443 availability checks.
3. DNS resolution check for `PUBLIC_URL` when a public hostname is configured.
4. Copy `deploy/.env.example` to `deploy/.env` only if `.env` does not exist.
5. Generate `SECRET_KEY`, `FERNET_KEY`, and `DB_PASSWORD` only when missing.
6. Pull the configured application, Postgres, Redis, and Caddy images.
7. Start the Compose stack.
8. Wait for `/health` with a bounded retry count.
9. Verify migration success through the API startup result.
10. Print the setup URL and next steps without printing generated secrets.

The script must stop and explain failure at each step. It must not use
`sudo`, delete files, reset volumes, or make outbound provider requests.

## Update flow

`update.sh` should:

1. Read the currently recorded and requested versions.
2. Record the previous version in local deployment state.
3. Pull the new application image.
4. Set `VERSION` and start API and worker.
5. Wait for `/health`.
6. Verify the containers remain running.
7. Write the new version only after successful health checks.
8. On migration or startup failure, set the previous image tag and restart.
9. Print rollback status and logs names without secrets.

Do not reset Postgres or Redis during update or rollback.

## Backup and restore flow

`backup.sh` should:

1. Run `pg_dump` inside or against the Postgres container.
2. Write a timestamped backup file to a deploy-owned backup directory.
3. Encrypt the backup at rest using a deployment-owned key or clearly document
   that the environment must provide encryption.
4. Retain 7 daily and 4 weekly copies.
5. Never include `.env`, container logs, email bodies, or support data.

`restore.sh` should be explicit, manual, and fail closed:

1. Require an exact backup file argument.
2. Require a written confirmation argument for a destructive restore.
3. Stop API and worker before restore.
4. Restore through a temporary Postgres-compatible process.
5. Run health checks and migrations after restore.
6. Never accept a backup path outside the resolved deployment backup directory.

## Support bundle flow

`support-bundle.sh` should collect:

- application, API, worker, database, Redis, and Caddy versions;
- a redacted `.env` shape with keys but no values;
- container status;
- migration state;
- recent container logs with secrets and email bodies redacted;
- disk usage and backup timestamps;
- license status without the license token.

The script must fail closed if redaction is unavailable. It must never collect
passwords, Fernet keys, JWT secrets, license tokens, SMTP credentials, or
message bodies.

## Health and observability

The initial `/health` response may remain:

```json
{"status": "ok"}
```

Before Module 12 is accepted, improve or add the deployment health checks enough
to verify:

- API process;
- database connectivity;
- Redis connectivity;
- worker heartbeat when an existing worker interface exposes one;
- recent backup timestamp when backup state is available.

Never expose secrets or full database connection strings in health output.

## Tests

Add focused no-network tests for:

1. Compose service names and required volumes.
2. Caddy routes `/api` to the API and `/` to static files.
3. `.env.example` contains required keys but no secret values.
4. Dockerfile uses a non-root user and has no copied `.env`.
5. Install script syntax and required preflight steps.
6. Install secret generation is never printed.
7. Update script records the previous version and contains an explicit rollback path.
8. Update script does not use a database reset or volume deletion.
9. Backup naming and 7-daily/4-weekly retention logic.
10. Restore script requires an exact resolved backup and explicit confirmation.
11. Support bundle redacts secret names, license tokens, and email bodies.
12. Health script retries within a bounded limit.

Shell tests may use local temporary directories and fake Docker commands. They
must not run real Docker containers, public DNS checks, backups, restores,
SMTP/IMAP calls, or LLM requests unless separately configured integration tests.

## Acceptance checklist

- [ ] Dockerfile builds the backend and both API/worker commands start.
- [ ] Compose starts Caddy, API, worker, Postgres, and Redis.
- [ ] API migrations run before Uvicorn starts.
- [ ] Caddy exposes HTTP/HTTPS routes without public database or Redis ports.
- [ ] Install script passes preflight and creates no secret values on terminal output.
- [ ] Install script reaches `/health` within its documented time limit.
- [ ] Update script successfully records and switches versions.
- [ ] Update failure restores the previous image tag.
- [ ] Rollback does not delete database or Redis volumes.
- [ ] Backup creates timestamped retention-limited files.
- [ ] Restore requires a resolved backup path and explicit confirmation.
- [ ] Support bundle contains no secrets, license tokens, or email bodies.
- [ ] Tests pass with fake providers and no external network calls.
- [ ] Documentation explains VPS requirements, install, update, rollback,
      backup, restore, and support-bundle export.

## Implementation order

1. Add the Dockerfile and `.dockerignore`.
2. Add Compose, Caddy, and `.env.example`.
3. Add an API/worker container health path and verify startup commands.
4. Add `install.sh` with bounded preflight and startup checks.
5. Add `update.sh` with explicit previous-image rollback.
6. Add `backup.sh` and manual `restore.sh`.
7. Add `support-bundle.sh` with redaction tests.
8. Add packaging documentation.
9. Run focused packaging tests and a local Compose validation.
10. Update [PROGRESS.md](../../PROGRESS.md) and [README.md](../../README.md).
