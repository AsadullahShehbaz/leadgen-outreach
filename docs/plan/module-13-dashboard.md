# Module 13 Plan - React Dashboard and Setup Wizard

Status: planned (2026-11-22).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 7, 20-22
(module 13).
Acceptance test from the design: **a user can complete a manual walkthrough
from first-run setup to campaign creation, lead review, draft approval, inbox,
analytics, compliance, and system status**.

## Goal

Build the dedicated-deployment React dashboard and the required dashboard API
surfaces:

1. Complete a first-run setup wizard for admin, license, connections, sender,
   responsibility acceptance, domain, and mailbox configuration.
2. Add authenticated dashboard pages for campaigns, leads, draft approval,
   inbox, analytics, compliance, and system status.
3. Add only the FastAPI routers and Pydantic schemas needed for those screens.
4. Build a static React application that Caddy serves at `/` and that calls
   the same deployment API through `/api/*`.
5. Keep secrets, message bodies, license tokens, and email bodies out of
   browser responses and logs.
6. Add focused no-network backend and frontend tests for the manual workflow.

## Out of scope

- Thompson sampling, the ICP ranking model, nightly optimizer, and weekly email
  report. Module 14 owns these features.
- Real source imports beyond existing CSV/website interfaces. The dashboard may
  trigger existing Module 9 jobs and display their results.
- New state-machine transitions. Existing enrollment status changes continue
  through `app/services/sequencing/state_machine.py`.
- SMTP/IMAP provider changes, send scheduling, bounce parsing, and reply
  classification. Modules 5-6 own them.
- Ed25519 license implementation changes. Module 13 displays the existing
  verified license state and does not accept or return raw license tokens.
- Automatic updates, off-box telemetry, open tracking, and auto-reply.
- Mobile native applications.

## Decisions

| Question | Decision |
|---|---|
| Frontend stack | React with Vite and JavaScript or TypeScript, selected only if the repository setup remains simple and beginner-friendly. |
| Backend prefix | Caddy strips `/api` and proxies to FastAPI; existing `/auth`, `/setup`, and `/system` routes keep their names. |
| Authentication | Use the existing OAuth2 password flow and JWT. Store the access token only in React memory/session state; never use URL parameters or logs. |
| Logout | Call the existing `/auth/logout` endpoint so the Redis-backed JWT is revoked. |
| Setup access | `/setup/status` is used to decide the wizard route. Mutating setup routes remain authenticated except initial admin creation. |
| Authorization | All dashboard and mutation endpoints require `get_current_user`; verify every object belongs to `user.workspace_id`. |
| Secret responses | Never return encrypted secrets or connection secret fields. Existing setup responses expose only kind/status. |
| Campaign data | Campaign API returns Pydantic DTOs that include campaign, sequence steps, and enrollment counts only; never vendor keys or raw credential data. |
| Lead import | Add CSV import only through the existing source interface/job, with a preview/count response and no synchronous external provider call. |
| Draft approval | Approval changes an enrollment from `drafted` to `queued` only through `state_machine.transition()`. Rejection goes through the existing terminal/rejected transition only if explicitly supported. |
| Inbox | The frontend reads existing message/enrollment data and reply classes; it does not implement or trigger provider sends or auto-replies. |
| Spend data | Reuse `SpendLedger` and spend helpers; show UTC today/month-to-date estimates and a clear cap-hit state. |
| Compliance | UI provides suppression lookup/add/remove, country/compliance settings, and forget-person actions. Suppression and forget-person remain compliance-owned services. |
| License/status | Show `valid`, `in_grace`, expiry, plan limits, customer, and reason. Never show the license token or public key. |
| System | Show version, health, license, backup status, update availability, and support-bundle guidance. Never include secrets or email bodies. |
| Error handling | Use one small React API client, explicit loading/error/empty states, and no silent success responses. |
| Styling | Use simple, local CSS and accessible semantic HTML. Do not add a component/UI framework that is not already required. |
| No-network tests | Backend tests use fake providers and database/session doubles. Frontend tests do not call real APIs or run real services. |

## Deliverables

```text
frontend/
  package.json
  vite.config.js or vite.config.ts
  index.html
  src/
    main.jsx or main.tsx
    App.jsx or App.tsx
    api/
      client.js/ts
    components/
      Layout.*       # nav and status alerts
      Loading.*
      ErrorState.*
      EmptyState.*
    pages/
      SetupWizard.*
      Login.*
      Dashboard.*
      Campaigns.*
      Leads.*
      DraftQueue.*
      Inbox.*
      Analytics.*
      Compliance.*
      System.*
  tests/
    ...

backend/
  app/
    schemas/
      campaign.py       # NEW
      lead.py           # NEW
      inbox.py          # NEW
      analytics.py      # NEW
      compliance.py     # NEW
      system.py         # NEW
    routers/
      connections.py    # NEW
      domains.py        # NEW
      mailboxes.py      # NEW
      campaigns.py      # NEW
      leads.py          # NEW
      inbox.py          # NEW
      analytics.py      # NEW
      compliance.py     # NEW
      system.py         # UPDATE
  tests/
    test_dashboard_api.py
    test_dashboard_workflow.py

deploy/
  docker-compose.yml    # UPDATE frontend build/public mount if needed
  Caddyfile             # VERIFY /api/* stripping and SPA fallback

docs/
  plan/module-13-dashboard.md
  dashboard-walkthrough.md
PROGRESS.md
README.md
```

## Backend API surfaces

Use one Pydantic response schema for every endpoint family. IDs remain UUID
strings in JSON.

### Setup and connections

Keep `/setup/status`, `/setup/admin`, `/setup/workspace`, `/setup/license`,
`/setup/connection`, `/setup/domain`, and `/setup/mailbox`.

Add or tighten:

- `GET /setup/status` includes setup completion and each required step.
- `GET /connections` lists configured kinds/status only.
- `GET /domains` lists domains and SPF/DKIM/DMARC flags.
- `GET /mailboxes` lists workspace mailboxes, status, cap, health, and domain.
- `PATCH /mailboxes/{id}` pauses or resumes a mailbox only through a small,
  authenticated mutation. It must not expose secrets.

DNS guidance is derived from the domain name and displayed by the frontend.
The backend must not claim DNS is green based on UI-only state.

### Campaigns

- `GET /campaigns`
- `POST /campaigns`
- `GET /campaigns/{id}`
- `PATCH /campaigns/{id}`
- `PUT /campaigns/{id}/sequence`
- `POST /campaigns/{id}/start` only if no license/source block applies

A campaign request contains name, product, ICP, compliance mode, approval setting,
and ordered sequence steps. Validate compliance mode and country rules on creation
and update. The campaign and sequence operations must be workspace-scoped.

Do not change enrollment state from this router except for enqueue/approval
operations that use existing services and `state_machine.transition()`.

### Leads

- `GET /leads`
- `POST /leads/import/csv`
- `POST /leads/{id}/verify`
- `POST /leads/{id}/forget`

The lead list includes verification status, ICP score, lawful basis, source,
and enrollment state without raw source payloads or credentials. CSV import
uses the existing source pipeline and license source gate. Verification uses the
existing verifier pipeline and spend cap.

`forget` delegates to the compliance forget-person service. Suppression must
occur before any personal-field wipe.

### Draft approval

- `GET /campaigns/{id}/drafts`
- `GET /campaigns/{id}/drafts/{enrollment_id}`
- `POST /campaigns/{id}/drafts/{enrollment_id}/approve`
- `POST /campaigns/{id}/drafts/{enrollment_id}/reject`

Approval must load the enrollment and campaign for the authenticated workspace,
verify the draft exists, and call `state_machine.transition(..., "queued", ...)`
only for the existing `drafted` state.

The draft response must include subject/body/claims. The body is email content,
so it is never logged or included in support bundles. Rejection uses the existing
`rejected` terminal transition for a clear `human_review_rejected` reason.

### Inbox

- `GET /inbox?limit=...`
- `GET /inbox/{message_id}`
- `PATCH /inbox/{message_id}` for local review metadata only

Use existing `Message`, `Enrollment`, `Lead`, and `LeadEmail` models. Do not
allow sending a reply through this API. The UI may show the existing classified
reply class and a suggested draft only if the existing model/data supports it;
there is no auto-reply.

### Analytics

- `GET /analytics/summary`
- `GET /analytics/campaigns/{id}`

Report positive replies and outcome counts, not open rates. Include:

- leads sourced;
- leads verified;
- drafts waiting approval;
- queued/sent/completed/replied/bounced/unsubscribed counts;
- UTC today and month-to-date spend estimates;
- current spend cap status;
- mailbox health summary.

No open-tracking pixel or open metric is introduced.

### Compliance

- `GET /compliance/suppression`
- `POST /compliance/suppression`
- `DELETE /compliance/suppression/{email_hash}`
- `PUT /compliance/settings`

Exact email additions are normalized and hashed by the existing suppression
service. Domain suppression remains supported. The UI never receives a reason
from a secret or vendor response.

The settings endpoint records sender identity, postal address, footer,
timezone, and campaign compliance defaults. It must reject campaign creation
when mandatory sender or responsibility data is incomplete.

### System

Keep `/system/license`.

Add:

- `GET /system/status` for API health summary, worker heartbeat if available,
  version, license summary, and last backup timestamp;
- `GET /system/version` for application and deployment image version;
- `GET /system/update` for update-available status if a safe status source exists;
  no automatic pull or update from the browser;
- `POST /support-bundle` or a download endpoint that delegates to the existing
  support-bundle behavior and redacts secrets/email bodies.

Do not expose `.env`, database URLs, Redis URLs, license tokens, public-key
material, or container logs containing message bodies.

## React screens

### 1. Login

- username/email and password form;
- loading and authentication error states;
- redirect to setup status or dashboard based on first-run state;
- logout calls the existing Redis-backed endpoint.

### 2. Setup wizard

Use a small ordered wizard backed by `/setup/status`:

1. Create admin and workspace.
2. Store and verify license.
3. Configure LLM and verifier connections.
4. Set sender identity, postal address, timezone, and responsibility acceptance.
5. Add sending domain and show SPF/DKIM/DMARC instructions.
6. Add mailbox, SMTP/IMAP connection, and warming status.
7. Set send and paid-work caps.
8. Show readiness and direct the user to create the first campaign.

No step may claim success after a failed API call. Secrets are submitted only
in setup requests and are never placed in browser state after success.

### 3. Dashboard

- license and setup alerts;
- send health, queue, replies, bounce alert, spend, and backup status;
- links to the next required action;
- no open metric or open trend.

### 4. Campaign builder

- campaign name;
- product/offering JSON as simple beginner-friendly fields;
- ICP fields;
- compliance mode;
- require approval;
- ordered sequence steps with step number and delay;
- save draft and start actions;
- clear blocking reasons for license, sender, domain, or mailbox readiness.

### 5. Lead list and import

- import CSV with existing source mapping;
- table/search/paging for company, person, title, country, ICP, verification,
  and lawful basis;
- verification and forget-person actions;
- raw source JSON stays hidden.

### 6. Draft approval queue

- list drafts waiting for human review;
- show subject and body on a dedicated review page;
- approve or reject with visible state result;
- never auto-send during personalization or approval UI calls.

### 7. Inbox

- list inbound messages and reply classes;
- show linked lead/campaign/enrollment context;
- provide review metadata only;
- no send-reply action and no auto-reply.

### 8. Analytics

- outcome funnel;
- positive reply and customer-won fields only when existing data supports them;
- spend today and month-to-date;
- cap-hit and mailbox-health warnings;
- campaign comparison without optimization claims.

### 9. Compliance

- suppression add/remove/list;
- sender identity and postal address;
- country/campaign compliance defaults;
- forget-person action;
- responsibility acknowledgement status.

### 10. System

- version and container health summary;
- license status;
- backup timestamp and update availability;
- support-bundle download/export if available;
- global kill-switch status without a browser control that bypasses compliance.

## Frontend behavior

The frontend is a small CRUD/read dashboard, not a second backend:

- Every mutation goes to FastAPI.
- Every workspace object is filtered server-side.
- UI state is never treated as license, suppression, DNS, health, or compliance
  authority.
- Status changes shown after approval are returned by the backend.
- API errors are rendered explicitly; no success-shaped fallback is allowed.
- Loading, empty, and unavailable states remain distinguishable.
- The dashboard does not cache or display credentials after setup.

## Deployment integration

The Vite build must produce static files in `frontend/dist`.

Module 13 updates the packaging seams so:

- the API image can remain unchanged;
- Caddy serves static files from `deploy/public` or the existing `web_dist`
  volume;
- `/api/*` strips `/api` and proxies to FastAPI;
- SPA routes fall back to `index.html`;
- Caddy does not serve source maps or environment files;
- Docker builds do not copy `.env`, `node_modules`, or frontend secrets.

The implementation may add a frontend build stage, but it must not duplicate
the existing API/worker application image or expose a public database/Redis
port.

## Tests

### Backend pytest

Add focused no-network tests for:

1. Login and dashboard route authorization.
2. Every list/mutation response hides credentials and license tokens.
3. Campaign and lead objects cannot cross workspace boundaries.
4. Campaign and sequence validation rejects invalid compliance states.
5. Lead CSV import uses fake source/provider interfaces and license gates.
6. Draft approval changes `drafted -> queued` exactly once.
7. Draft rejection changes to `rejected` only for a valid enrollment.
8. Inbox endpoints expose no send or auto-reply action.
9. Suppression endpoints delegate to the existing suppression service.
10. Forget-person suppresses before wiping personal fields.
11. Analytics include UTC spend summaries and no open metric.
12. System status/license/backups redact secrets and message bodies.
13. Malformed API inputs return Pydantic/FastAPI errors, not silent success.
14. Caddy route `/api/*` strips prefix and SPA fallback remains intact.

### Frontend tests

Add focused tests for:

1. Login and setup-status redirect.
2. Setup wizard step progression and failure states.
3. Campaign create/sequence validation.
4. Lead import and verification states.
5. Draft approve/reject confirmation and no duplicate approval.
6. Inbox renders reply classes without a send-reply control.
7. Analytics spend/license/bounce alerts.
8. Compliance add/remove/forget-person actions.
9. System status redaction and update-available behavior.
10. Loading, empty, API-error, and network-error states.

Tests must use fake API responses and never call real mail, LLM, DNS, SMTP,
IMAP, Postgres, Redis, or third-party providers.

## Implementation order

1. Add Pydantic dashboard schemas and workspace-scoped campaign/lead routes.
2. Add mailbox/domain/connection read routes and tighten existing setup APIs.
3. Add draft approval routes through `state_machine.transition()`.
4. Add lead import, inbox read, compliance, analytics, and system read routes.
5. Start the React/Vite app with the shared API client and auth context.
6. Add login and setup wizard.
7. Add campaign builder and lead list/import.
8. Add draft queue and inbox.
9. Add analytics, compliance, and system pages.
10. Integrate the static build with Caddy and Compose.
11. Run focused backend and frontend tests.
12. Complete a manual local walkthrough with Fake providers.
13. Update `PROGRESS.md` and `README.md`.
14. Mark Module 13 implemented only after the acceptance walkthrough passes.

## Acceptance checklist

- [ ] First-run setup reaches complete status without exposing secrets.
- [ ] Login/logout and workspace isolation work through the existing JWT flow.
- [ ] Domain and mailbox status are visible with clear DNS readiness.
- [ ] Campaign and sequence creation works and respects compliance/license rules.
- [ ] Lead CSV import and verification use fake providers and spend caps.
- [ ] Draft approval enqueues exactly once through the state machine.
- [ ] Inbox displays reply/bounce context without a send or auto-reply control.
- [ ] Analytics show outcomes and spend with no open metric.
- [ ] Suppression and forget-person actions preserve compliance behavior.
- [ ] System page shows redacted license, health, backup, and update information.
- [ ] Caddy serves the React app and `/api/*` routes to FastAPI.
- [ ] Frontend and backend tests pass without external network calls.
- [ ] Manual walkthrough is documented and can be repeated on a fresh stack.
