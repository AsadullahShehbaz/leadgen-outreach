# Module 14 Plan - Optimizer + Weekly Report

Status: planned (2026-11-22).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 16, 19,
20, 21, and 22 (module 14).
Acceptance test from the design: **variant traffic shifts only after the
minimum sample threshold, the lead queue reorders from positive-reply
history, and a weekly report is generated without opening pixels or real
email/network calls**.

## Goal

Add the simple optimizer described in the design:

1. Track A/B variants by subject, opener, and call to action.
2. Use Thompson sampling only after a configured minimum sample threshold.
3. Reorder campaign lead queues using a beginner-friendly positive-reply
   predictor based on lead features.
4. Generate a weekly workspace report with best segment, best angle, positive
   reply count/rate, customers won, and estimated cost per positive reply.
5. Send the report through the existing `MailProvider` interface when a
   client mailbox and report address are configured.
6. Expose read-only optimizer status and report preview data in the existing
   analytics/dashboard surface.
7. Keep no-network tests deterministic with fakes and in-memory stores.

## Out of scope

- Open tracking, conversion pixels, or mailbox-provider tracking.
- Automatic sending of campaign variants outside the existing `send_due`
  and state-machine flow.
- Neural ranking models or a new ML platform.
- Shared-tenancy optimization: every query must remain workspace-scoped.
- Real SMTP/IMAP, Redis, Postgres, or LLM calls in tests.
- A public SaaS control plane or cross-client data sharing.
- Adding new weekly-report recipients as a new credential/connection type
  unless the existing connection model can represent it safely.

## Decisions

| Question | Decision |
|---|---|
| Variant assignment | Use `Enrollment.variant_id` and `Message.variant_id` already in the schema. The variant is selected once and remains attached to the sequence. |
| Variant storage | Reuse `Experiment`; do not add a second experiment or variant table unless tests or migrations prove one is required. |
| Minimum sample | Default to 30 sent positive/negative observations per variant. Make it configurable in application settings and show the threshold in status output. |
| Bandit algorithm | Thompson sampling with one beta-Bernoulli arm per variant. Update arm successes and failures from positive replies and completed/no-reply outcomes only. |
| No-reply handling | A variant observation becomes negative only after a configured outcome window, so a recent send is not mislabeled immediately. |
| ICP ranking | Use a transparent, dependency-light logistic model or a small deterministic feature-weight fallback if training data is insufficient. Do not add scikit-learn unless the repository explicitly chooses it. |
| Training data | Use campaign/workspace leads plus enrollment reply outcome, industry, size, role/title, and country. Never include email address, raw provider data, or credentials in model data. |
| Customer won | Start with existing `replied`/classification evidence only. A reply class of `interested` or `question` is a positive reply signal; no invented "customer won" field is allowed. |
| Queue reorder | Produce a ranking score per lead and apply it to pending enrollments. Never bypass compliance, license, suppression, windows, or send caps. |
| Report cadence | One ARQ cron job weekly, with `unique=True`. Record and expose last-attempt/last-success timestamps; do not silently resend. |
| Report delivery | Use `FakeMailProvider` for tests and the existing outbound `MailProvider` interface for production. It is a report, not a prospect email. |
| Spend cost | Reuse `SpendLedger`; report only estimated cost by kind and avoid exposing stored credentials or raw ledger details. |
| Privacy | No cross-workspace models, report data, or experiment scores. Report body contains aggregate campaign results only. |
| Status changes | No optimizer code may change `Enrollment.status` directly. Existing state-machine transitions remain the only way to change status. |

## Deliverables

```text
backend/
  app/
    services/
      agents/
        optimizer.py             # NEW: variant, ranking, and report calculations
    routers/
      analytics.py               # UPDATE: optimizer status and report preview
    workers/
      arq_settings.py            # UPDATE: weekly report cron
      jobs.py                    # UPDATE: optimizer/report job entry points
  tests/
    test_optimizer.py            # NEW
    test_weekly_report.py        # NEW

docs/
  plan/module-14-optimizer-weekly-report.md
PROGRESS.md
README.md
```

The implementation may need a small model or report migration only if the
existing `experiments.stats` JSON and `SpendLedger`/`Event` data cannot
represent enough state. A migration is not assumed; the plan must inspect and
reuse existing storage first.

## Existing surfaces to reuse

- `app/models/enrollment.py`
  - `Enrollment.variant_id`
  - `Enrollment.status`
  - `Message.variant_id`
- `app/models/analytics.py`
  - `Experiment.campaign_id`, `Experiment.kind`, `Experiment.variants`,
    and `Experiment.stats`
  - `SpendLedger.kind`, `day`, `units`, and `est_usd`
- `app/models/lead.py`
  - lead industry/company, size, role/title, country features
- `app/services/sequencing/state_machine.py`
  - enrollment status transitions
- `app/services/sequencing/send_due.py`
  - pre-send license, suppression, window, and cap checks
- `app/services/budget/spend_caps.py`
  - UTC spend summary and ledger storage
- `app/services/mail/base.py`
  - `MailProvider` interface
- `app/routers/analytics.py`
  - existing workspace dashboard summary
- `app/workers/arq_settings.py`
  - worker and cron registration

## Variant experiment design

Each experiment should be campaign-scoped and contain three kinds:

1. `subject`
2. `opener`
3. `cta`

The implementation should keep a simple, explicit data shape:

```python
{
    "variant_id": "subject-a",
    "sent": 0,
    "successes": 0,
    "failures": 0,
    "beta_alpha": 1.0,
    "beta_beta": 1.0,
}
```

Rules:

- Assign one variant per kind only for new pending enrollments.
- A variant remains fixed once assigned to an enrollment.
- Do not divide an enrollment by variant unless an explicit experiment has
  three arms and the campaign opts into it.
- Before the minimum sample threshold, use round-robin or the lowest-observed
  arm count so all variants collect enough observations.
- After the threshold, return a Thompson-sampling choice.
- Updates must be idempotent by stable reply/message/event identifiers.
- A repeated optimizer job must not add duplicate successes or failures.

## Positive-reply and ICP ranking

Add pure helper functions for:

1. Encoding only explicit lead features: industry/company type, size, role,
   title, and country.
2. Calculating a bounded score from historical positive replies.
3. Applying a campaign's variant or angle when one is known.
4. Returning the best segment and best angle for reporting.

Before enough positive outcomes exist, return the existing deterministic
`icp_score` order or a neutral score. The optimizer must not invent data.
If size or industry is missing, omit that feature rather than treating it as
zero or unknown.

Queue reordering should produce a sorted list for pending rows only. It must
not change database status or scheduling values. The caller may use the score
only when choosing among leads already eligible for sequencing.

## Weekly report

The report should contain:

- reporting week in UTC
- workspace/campaign name
- total sent
- positive replies
- positive reply rate
- best segment
- best angle
- estimated cost by `llm`, `verify`, and `source`
- estimated cost per positive reply
- at least one short action/recommendation

Do not use opens or link clicks as success metrics.
Do not include lead names, email addresses, raw drafts, subjects, message
bodies, credentials, license tokens, or suppression hashes.

The report can be exposed as a JSON preview through analytics. Sending is
triggered only by a dedicated ARQ job or cron. The report should use a
workspace-level recipient setting if already available; otherwise it is
marked preview-only and the plan must stop rather than invent a recipient
field.

## Worker and scheduling

Add a pure/report function and an ARQ wrapper:

```text
optimizer_engine(...) -> result
weekly_report(ctx) -> result
```

The weekly cron should:

- run once per week at a configured UTC weekday/hour;
- use `unique=True`;
- create no report if no positive outcomes or sends exist;
- use UTC for reporting windows;
- close only after the report preview and optional send status are persisted
  or deterministically recorded.

If sending through a real mailbox fails, the report attempt must be retryable
and must not alter enrollment or lead state.

## API surfaces

Keep the existing `/analytics/summary` response compatible.

Add:

- `GET /analytics/optimizer`
- `GET /analytics/report/preview`

Both endpoints require `get_current_user`, verify workspace ownership, and
return only aggregates. Do not expose raw experiment state, lead PII, message
bodies, public keys, or license tokens.

## Tests

Add focused no-network pytest coverage:

1. Thompson sampling stays round-robin before the minimum sample.
2. Thompson sampling can select a higher posterior arm after the threshold.
3. No duplicate arm success/failure updates on replay.
4. Pending leads are ranked deterministically.
5. Missing lead features do not add fake scores.
6. Positive reply counts use `interested`/`question` only through configured
   classification values.
7. Negative outcome is not recorded before the configured outcome window.
8. Weekly report has zero cost/zero reply safe output.
9. Report output never includes email addresses, message bodies, credentials,
   or license tokens.
10. Cron wrapper uses fake session/store/provider and is idempotent.
11. Workspace A cannot read or rank Workspace B experiment or lead data.
12. Optimizer output never changes enrollment status directly.

Use existing fakes for mail and providers. Do not use real LLM, SMTP, IMAP,
Redis, or DNS in tests.

## Implementation sequence

1. Inspect current `Experiment`, `Enrollment`, `Message`, `Event`,
   `SpendLedger`, and analytics router usage.
2. Add pure variant and ranking helpers with strict input validation.
3. Add workspace-scoped database queries for outcomes and spend.
4. Wire ranking to analytics/report data without changing send state.
5. Add the weekly report builder and report preview endpoint.
6. Add the ARQ job and one weekly cron entry.
7. Add fake mail/report tests and replay/idempotency tests.
8. Run the smallest focused optimizer and worker test set.
9. Run the existing backend suite once the focused set passes.
10. Update the dashboard analytics page only if the existing dashboard surface
    can display aggregate optimizer/report status cleanly.

## Acceptance checklist

- [ ] A/B variants are campaign-scoped and assigned only to pending work.
- [ ] Minimum sample threshold prevents early Thompson-sampling shifts.
- [ ] Replay does not double-count success or failure outcomes.
- [ ] Lead ranking is deterministic and workspace-scoped.
- [ ] Missing features never invent score contributions.
- [ ] Positive replies and customer-won reporting use existing evidence.
- [ ] Weekly report includes UTC week, sends, positive replies, best segment,
  best angle, spend, cost per positive reply, and a safe action.
- [ ] Report preview is accessible only to the workspace owner/user.
- [ ] Report delivery uses `MailProvider` and passes `FakeMailProvider` tests.
- [ ] No open pixels, real email sends, or auto-replies are added.
- [ ] No optimizer code changes enrollment status directly.
- [ ] No secrets or PII appear in report output or logs.
- [ ] Focused optimizer/report tests pass.
- [ ] Full pytest suite passes or only documented environment integrations
  remain skipped.
