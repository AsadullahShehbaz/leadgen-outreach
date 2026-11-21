# Module 7 Plan - Auth + Setup Wizard API

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 7, 9, 20, and 22
(module 7).
Acceptance test from the design: **secrets are never returned by the API**.

## Goal

Implement the first-run administration and authentication API:

1. Add password hashing and JWT access-token helpers.
2. Add `/auth/token`, `/auth/me`, `/auth/logout`, and `/auth/password`.
3. Add Redis JWT revocation for logout.
4. Add `/setup/status` and the first-run `/setup` endpoints.
5. Create the initial admin and one workspace.
6. Store LLM, verifier, SMTP/IMAP, and optional source credentials with Fernet.
7. Require sender identity, postal address, and responsibility acceptance.
8. Store the supplied license token for later validation in Module 11.

## Out of scope

- Ed25519 license verification. Module 11 owns verification and soft enforcement.
- Real SMTP test sends or IMAP fetch tests. Module 6's provider seam is unchanged.
- Real DNS SPF/DKIM/DMARC checks. Module 7 stores domain records only.
- React setup and dashboard screens.
- Lead sources, campaign APIs, lead verification, spend caps, and language-agent APIs.
- Real-time notification and support-bundle features.
- Optional TOTP enrollment. The existing `totp_secret` column remains unused.
- Google OAuth and API-key OAuth flows.

## Decisions

| Question | Decision |
|---|---|
| Authentication flow | OAuth2 password form at `/auth/token`, with a Bearer JWT access token. |
| Password hashing | Passlib bcrypt. Never store or return a plain password. |
| JWT | Signed HS256 access token with `sub`, `jti`, `exp`, `workspace_id`, and `role` claims. |
| Token lifetime | 30-minute access token by default, configurable by environment. |
| Logout | Redis stores the token `jti` as revoked until `exp`; Redis failure fails closed for logout verification. |
| Redis unavailable | Authentication can remain unavailable rather than accepting an unverifiable revoked token. |
| Initial setup | `/setup/admin` creates the first admin only when no `users` row exists. |
| Workspace scope | Every dedicated deployment has one primary workspace; API rows are always scoped to it. |
| Password change | `/auth/password` requires the current password and a stronger replacement. |
| Setup responsibility | Workspace creation/update requires `accept_responsibility = true`. |
| Setup records | `/setup/status` reports booleans, never secrets or user password hashes. |
| Stored credentials | Fernet-encrypted `Connection.encrypted_secret`; no credential is returned after saving. |
| Connection kinds | `llm`, `verifier`, `apollo`, `apify`, `smtp`, `imap`. Reject unknown kinds. |
| Connection upsert | One connection per `(workspace_id, kind)` is retained. |
| SMTP/IMAP secrets | One secret envelope may hold provider fields, but the API never returns it. |
| License storage | Store the supplied license token in `LicenseState`; do not claim it is valid until Module 11. |
| Sender identity | `sender_identity` and `postal_address` are both mandatory before setup completes. |
| Domains/mailboxes | `/setup/domain` and `/setup/mailbox` may create records, but no DNS or provider test is required in this module. |
| TOTP | No new dependency or endpoint in Module 7; this remains a later optional security feature. |
| Migration | Add a small setup marker and responsibility timestamp to `workspaces` if no existing field can represent the audit. |
| Test providers | Fake Redis, fake async database seams, no network SMTP/IMAP, and no real credentials. |

## Deliverables

```text
backend/
  app/core/
    security.py              # NEW: password, JWT, current-user dependency, Fernet helpers
  app/schemas/
    auth.py                  # NEW: login response, user, password-change schemas
    setup.py                 # NEW: setup status and wizard request/response schemas
  app/routers/
    auth.py                  # NEW: token, me, logout, password endpoints
    setup.py                 # NEW: first-run wizard endpoints
  app/models/
    workspace.py             # update only if setup/audit columns are added
  alembic/versions/
    0002_setup_audit.py      # NEW only if workspace setup columns are needed
  tests/
    test_auth.py             # NEW
    test_setup.py            # NEW
docs/plan/
  module-07-auth-setup.md    # this plan
PROGRESS.md
README.md
```

Wire both routers into `app/main.py`. Do not expose raw database objects.

## Environment

Add or document these settings in `Settings` and `.env.example`:

- `SECRET_KEY`: JWT signing key; fail startup if unset in production.
- `FERNET_KEY`: URL-safe Fernet key; fail setup if invalid.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: default `30`.
- `REDIS_URL`: existing Redis connection for logout revocation.
- `PUBLIC_URL`: existing public application URL.

Do not use placeholder secrets as working production credentials. `.env.example`
must contain clearly marked empty or generated-by-installer values.

## API contracts

### Auth

#### `POST /auth/token`

OAuth2 password form:

```text
username=<email>
password=<password>
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

Behavior:

- Normalize the email before lookup.
- Return `401` for unknown user or wrong password.
- Return no password hash or password details.
- Reject configured TOTP users as unsupported until TOTP is implemented, rather
  than silently bypassing 2FA.

#### `GET /auth/me`

Return:

```json
{
  "id": "<uuid>",
  "workspace_id": "<uuid>",
  "email": "admin@example.com",
  "role": "admin"
}
```

#### `POST /auth/logout`

Require a valid access token, extract `jti`, and add it to the Redis revoked set
with TTL no longer than the token's remaining lifetime.

An already revoked token must be rejected on subsequent protected requests.

#### `POST /auth/password`

Requires the current password and a new password. Hash the replacement and commit
it before returning success.

### Setup

#### `GET /setup/status`

Publicly return only first-run readiness fields:

```json
{
  "initialized": true,
  "admin_created": true,
  "workspace_created": true,
  "license_stored": false,
  "llm_configured": false,
  "verifier_configured": false,
  "sender_configured": false,
  "responsibility_accepted": false,
  "complete": false
}
```

No connection secret, license token, password hash, or mailbox password is returned.

#### `POST /setup/admin`

Create the initial workspace and admin together. The response contains only the
workspace ID, user ID, email, and role.

- Reject setup if any `User` already exists.
- Validate email and password.
- Hash the password.
- Create the workspace with the supplied name.
- Create the first user as `admin`.
- Commit atomically.

#### `POST /setup/workspace`

Require authentication and update:

- workspace name,
- sender identity,
- postal address,
- timezone,
- responsibility acceptance.

Require `accept_responsibility = true`. Missing sender identity or postal address
raises `422`.

If added to the workspace model, persist `setup_responsibility_accepted_at` and
`setup_completed_at` only after all required setup fields are present.

#### `POST /setup/license`

Require authentication and store `license_token` in `LicenseState`. Module 7 does
not verify or set a false valid state. Existing license rows should be replaced or
the newest token should be selected by `created_at`.

#### `POST /setup/connection`

Require authentication and accept a kind plus a JSON secret object.

- Encrypt JSON or provider secret fields with Fernet.
- Upsert by `(workspace_id, kind)`.
- Set `status = "configured"`.
- Never return `encrypted_secret`.

The plaintext secret object exists only in the request and memory. Never log it.

Supported secret shapes:

- `llm`: `base_url`, `api_key`, `model_small`, `model_large`
- `verifier`: `provider`, `api_key`
- `apollo`: `api_key`
- `apify`: `api_token`
- `smtp`: `host`, `port`, `username`, `password`
- `imap`: `host`, `port`, `username`, `password`

#### `POST /setup/domain`

Require authentication and create or update the workspace domain. Validate the
domain and store it; DNS flags remain false until a future DNS check.

#### `POST /setup/mailbox`

Require authentication and create or update a mailbox address, domain ID, and
daily cap. Do not activate it in this module; keep `status = "warming"` until
provider verification and warm-up rules are implemented.

### Protected route dependency

Define `get_current_user` as the only application dependency for protected routes.
It must:

1. Read and validate the Bearer token.
2. Check Redis revocation.
3. Resolve the user and workspace.
4. Reject mismatched or missing workspace scope.

No protected setup or future router should trust a workspace ID supplied by a
client instead of the authenticated workspace claim and database row.

## Security helpers

Implement these small functions:

```python
def hash_password(password: str) -> str: ...
def verify_password(password: str, password_hash: str) -> bool: ...
def create_access_token(user: User, expires_minutes: int) -> str: ...
async def is_token_revoked(redis, jti: str) -> bool: ...
async def revoke_token(redis, jti: str, ttl_seconds: int) -> None: ...
def encrypt_secret(fernet_key: str, secret: dict) -> str: ...
def decrypt_secret(fernet_key: str, encrypted: str) -> dict: ...
```

Password minimum length and email validation use Pydantic or existing library
patterns. No credentials belong in test fixtures as real provider keys.

## Setup transaction rules

- Initial admin and workspace creation commit together.
- Workspace and responsibility updates commit together.
- Connection upserts commit once.
- License token storage is independent of license validity.
- Setup status and credential endpoints never expose secret data.
- License problems never alter auth or suppress compliance behavior.
- A setup API call must not activate sending or a mailbox.

## Migration plan

If setup audit fields are needed, add a 0002 migration with:

- `setup_responsibility_accepted_at: DateTime(timezone=True) | None`
- `setup_completed_at: DateTime(timezone=True) | None`

Do not add a plaintext responsibility note or license token to `workspaces`.

If the migration is avoided, document that responsibility acceptance is validated
on each `/setup/workspace` call and setup completion is derived without a
persistent audit timestamp. The recommended implementation is the migration,
because the design requires responsibility acceptance.

## Tests

### `test_auth.py`

- Password hashing verifies and different plain text does not match.
- Same password produces a non-plain bcrypt hash.
- Access JWT contains expected subject and workspace claims.
- Expired JWT is rejected.
- Revoked JWT is rejected through fake Redis.
- Logout blacklists the `jti` and does not return the token.
- `/auth/token` returns a Bearer token for valid credentials.
- Wrong password and unknown email return `401`.
- `/auth/me` returns the current user and workspace only.
- Password change validates the old password.
- Password change rejects weak or unchanged passwords.
- Protected routes reject missing, malformed, or mismatched workspace context.
- No auth response includes password or `password_hash`.

### `test_setup.py`

- `/setup/status` hides secrets and license tokens.
- First setup creates one workspace and admin atomically.
- Re-running admin setup is rejected.
- Missing sender identity or postal address is rejected.
- Responsibility acceptance is mandatory.
- License token is stored but not returned.
- LLM, verifier, SMTP, and IMAP connections round-trip only through encryption.
- Unknown connection kind is rejected.
- API response never contains `encrypted_secret`, API key, SMTP password, or
  Fernet ciphertext.
- Domain can be created with DNS flags false.
- Mailbox is created as `warming`, not `active`.
- Workspace scope prevents an admin from modifying another workspace.
- Setup has no external network calls or real mail sends.
- Fake Redis/crypto dependencies are enough to run the complete suite.

## Implementation order

1. Add `SECRET_KEY`, `FERNET_KEY`, and access-token settings.
2. Add `app/core/security.py`.
3. Add auth Pydantic schemas and `/auth` router.
4. Add JWT revocation with fakeable Redis helpers.
5. Add setup Pydantic schemas.
6. Add initial workspace and admin setup endpoint.
7. Add setup status and responsibility/sender fields.
8. Add encrypted connection upsert and license-token storage.
9. Add domain and mailbox setup records.
10. Add migration only if setup audit fields are needed.
11. Register routers in `app/main.py`.
12. Write focused auth and setup tests.
13. Run the focused Module 7 suite.
14. Run the full `pytest` suite and confirm Modules 1-6 remain green.
15. Update `PROGRESS.md` and `README.md`.

## Acceptance checklist

- [x] Passwords are hashed and never exposed.
- [x] `/auth/token` implements OAuth2 password flow.
- [x] JWT claims identify user, workspace, role, expiry, and `jti`.
- [x] Logout revokes JWT through Redis.
- [x] Revoked and expired tokens are rejected.
- [x] Initial setup creates an admin and workspace atomically.
- [x] `/setup/status` gives readiness without secrets.
- [x] Sender identity and postal address are required.
- [x] Responsibility acceptance is mandatory.
- [x] License token is stored without false verification.
- [x] All credential types are encrypted with Fernet.
- [x] API responses never return plaintext or encrypted credentials.
- [x] Domain and mailbox setup records work without network checks.
- [x] Mailboxes start in `warming`, never `active`.
- [x] Tests use fake Redis and never touch real credentials or email.
- [x] Full suite passes.
- [x] `PROGRESS.md` marks Module 7 done and points to Module 8.

## Risks to watch

- **Plaintext credentials:** Encrypt before database add and never include a
  `Connection` model directly in a response.
- **Secret leakage:** Never log request bodies, JWT signing keys, Fernet keys,
  license tokens, SMTP passwords, or API keys.
- **Workspace confusion:** Derive workspace scope from the authenticated user,
  not from a caller-supplied UUID.
- **Logout race:** Enforce revocation before every protected request.
- **Weak setup state:** Require one-time admin setup, sender identity, postal
  address, and responsibility acceptance.
- **License coupling:** Storing a token is not verification; Module 11 remains
  responsible for validity.
- **TOTP bypass:** Until implemented, fail closed for a user that has
  `totp_secret` configured.
- **Password migration:** Never hash already-hashed values twice.
- **Redis failure:** Fail closed for token revocation checks.
