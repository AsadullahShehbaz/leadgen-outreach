# Module 10 Plan - LangGraph Personalization Agent

Status: implemented (2026-11-21).
Design reference: `docs/leadgen-system-design-v2.md`, Sections 13-14 and 22
(module 10).
Acceptance test from the design: **the critic rejects invented claims**.

## Goal

Implement the personalization agent behind a fakeable LLM interface:

1. Add an `LLMClient` interface and OpenAI-compatible client adapter.
2. Define a Pydantic `Draft` schema and a LangGraph personalization state.
3. Implement `score_icp -> research -> pick_angle -> draft -> critic -> save`.
4. Use the critic to reject unsupported claims, spam language, fake familiarity,
   excessive length, and multiple calls to action.
5. Reserve LLM spend through Module 8 before each paid LLM call.
6. Save approved drafts as `drafted` enrollment state without sending email.
7. Use fake LLMs and fake research context in tests; never call a real provider.

## Out of scope

- Lead sourcing and verification implementation; those interfaces and pipelines are
  in Module 9.
- SMTP/IMAP sending and inbox processing; those are Modules 5-6.
- Ed25519 license enforcement; Module 11 owns license checks.
- React campaign drafting screens; Module 13 owns UI/API surfaces.
- Real company/news web crawling if a campaign-safe research interface is not
  available.
- Auto-reply, open-tracking, image tracking, or outbound send scheduling.
- A/B bandit optimization or nightly campaign ranking; Module 14 owns optimization.

## Decisions

| Question | Decision |
|---|---|
| Agent framework | LangGraph with a small typed state and explicit graph nodes. |
| LLM interface | External calls go through `LLMClient.complete(...)`; no direct OpenAI calls inside graph nodes. |
| Default provider | OpenAI-compatible HTTP adapter configured from existing setup connection fields. |
| Research | Fetch only approved/cached public context through a small `ResearchClient` seam. |
| Structured output | `Draft` is a Pydantic model; provider output must validate before use. |
| Critic behavior | Fail closed on unsupported claims, invalid schema, or unavailable context. |
| Retry policy | Maximum 2 draft retries after critic rejection. |
| Final failure | Reject the enrollment or route it to human review; do not invent or send a draft. |
| Approval | Preserve `Campaign.require_approval`; personalization creates drafts only. |
| State changes | Call `transition()` for every enrollment status change. |
| Spend | Reserve LLM usage through Module 8 before every paid LLM call. |
| Client credentials | Resolve LLM credentials from the encrypted setup connection, not environment-shared keys. |
| Logs | Log node names and enrollment IDs only; never log prompt text, full context, draft body, or secrets. |

## Deliverables

```text
backend/
  app/services/agents/
    __init__.py
    llm.py               # NEW: LLMClient protocol and OpenAI-compatible adapter
    research.py           # NEW: research interface and fake/in-memory implementation
    personalize_graph.py  # NEW: LangGraph nodes and graph construction
    prompts/              # NEW: versioned prompt text files
      system.md
      draft.md
      critic.md
  app/workers/
    jobs.py               # UPDATE: personalize job entry point
  tests/
    test_personalization.py
docs/plan/
  module-10-langgraph-agent.md
PROGRESS.md
README.md
```

No database migration is required unless implementation reveals that no existing
campaign or enrollment fields can store the finalized draft.

## Interfaces

```python
class Draft(BaseModel):
    subject: str = Field(max_length=70)
    body: str = Field(max_length=900)
    claims: list[str]


class CriticResult(BaseModel):
    passed: bool
    reasons: list[str] = []


class DraftState(TypedDict):
    lead: dict
    campaign: dict
    context: str
    angle: str
    draft: Draft | None
    critic: CriticResult | None
    attempts: int


class LLMClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list,
        schema: type[BaseModel] | None,
    ) -> Any:
        ...


class ResearchClient(Protocol):
    async def research(self, company_domain: str) -> str:
        ...
```

Keep Pydantic schemas explicit and validate every provider result. Do not pass raw
provider objects through graph state.

## Graph behavior

The graph must be small and easy to follow:

```text
score_icp -> research -> pick_angle -> draft -> critic
                                           | pass  -> save
                                           | fail  -> draft retry (maximum 2)
                                           | final -> reject or human review
```

### `score_icp`

- Use existing lead and campaign fields only.
- Reuse or confirm the simple transparent ICP score from Module 9.
- Do not introduce an external ML model.
- Store the score on `Lead`; do not change enrollment status.

### `research`

- Accept the lead's approved company domain and campaign context.
- Retrieve a bounded public context string through `ResearchClient`.
- Cache successful research where the existing database/LLM implementation can
  safely store text. No credentials or secrets belong in cached context.
- On research failure, continue with an empty context only if the draft critic can
  verify that no unsupported claim is used. Default to human review.

### `pick_angle`

- Select a short outreach angle from campaign data and factual research context.
- Output plain graph state, not a direct email draft.

### `draft`

- Use the configured small or large model according to task cost.
- Require `Draft` Pydantic validation.
- Include every factual claim in `Draft.claims`.
- The LLM must not add the sender footer or opt-out link.

### `critic`

The critic must reject a draft when:

- any claim in `claims` is not supported by `context`;
- the body is longer than about 120 words;
- the subject is longer than 70 characters;
- the body is longer than 900 characters;
- there is not exactly one clear CTA;
- the draft mentions the client's real product only through unsupported claims;
- it contains common spam-trigger phrases or pressure language;
- it claims familiarity or a relationship that is not in the context;
- it invents a person, event, metric, product feature, or relationship;
- it includes or attempts to create a footer or opt-out link.

For test determinism, implement claim support as a pure helper:

```python
def critic_rejects_unbacked_claims(draft: Draft, context: str) -> CriticResult:
    ...
```

The provider critic may add judgments, but a pure local safety check must remain
the final gate.

The footer is always appended by Module 5 code, never by the graph.

### `save`

- Save one approved subject/body draft associated with the lead or enrollment.
- Transition `verified -> drafted` with `transition()`.
- If `Campaign.require_approval` is true, leave the enrollment out of `queued`
  and require explicit dashboard approval in Module 13.
- If a later module already stores drafts as JSON on the enrollment/campaign model,
  preserve that shape instead of adding a separate table.

If no existing field can store the approved draft, document the minimal schema
change and add a migration before implementation. Do not invent a second status
machine or set `Enrollment.status` directly.

## Spend and provider behavior

Before every `LLMClient.complete()` call:

1. Build `SpendLimits` from settings.
2. Estimate `units` and `est_usd` explicitly.
3. Call Module 8 `reserve_usage()` for `kind="llm"`.
4. Commit the reservation before provider work.
5. On a cap hit, pause personalization and mark the draft for later retry.
6. On provider/store failure, fail closed and add no false approved draft.

The reservation remains counted after provider failure, as defined in Module 8.
Do not record usage twice.

LLM failures must not block suppression, bounce handling, unsubscribe handling, or
send-compliance paths.

## Prompt storage

Add versioned prompt files under `app/services/agents/prompts/`:

- `system.md`: product and safety role.
- `draft.md`: strict `Draft` output instructions.
- `critic.md`: claim-support and style criteria.

Prompts should use placeholders, not hardcoded client credentials or secrets.
Drafting prompts must not say that the LLM should add an email footer.

## Enrollments

The personalization job should operate on eligible verified lead emails:

1. Load one enrollment and campaign context in the workspace scope.
2. Refuse to personalize if the enrollment is suppressed or no longer `verified`.
3. Run the graph exactly once for an initial batch or until a stored retry marker
   prevents duplicate work.
4. On accepted output:
   - save the draft;
   - call `transition(..., "drafted", "personalization approved")`.
5. On human-review rejection:
   - keep the enrollment `verified`;
   - record a clear reason on the existing event or draft store.
6. Never queue or send here.

Idempotent reruns must return the existing approved draft and must not create
duplicate events or paid LLM calls.

## Tests

Create focused `tests/test_personalization.py` coverage:

- `Draft` rejects a subject longer than 70 characters.
- `Draft` rejects a body longer than 900 characters.
- A critic accepts every claim when each sentence is supported by context.
- A critic rejects an invented customer, metric, feature, or event.
- A critic rejects a draft with no CTA or multiple CTAs.
- A critic rejects fake familiarity and unsupported product claims.
- A critic rejects a draft containing common spam-trigger language.
- A graph draft retry succeeds after a critic failure and stops after 2 retries.
- A final critic failure does not queue or send and does not transition out of
  `verified`.
- The graph returns a Pydantic `Draft` only after local and schema validation.
- Missing required context fails safely and routes to human review.
- LLM spend cap hit makes no provider call.
- Store/provider failure raises explicitly and creates no approved draft.
- A rerun is idempotent and does not call the LLM or create duplicate events.
- A saved approved draft transitions `verified -> drafted` only through
  `transition()`.
- `require_approval=true` leaves the enrollment out of `queued`.
- No test performs network I/O or uses a real LLM account.

## Implementation order

1. Add `llm.py` with `LLMClient`, the OpenAI-compatible adapter, and a fake client.
2. Add `research.py` with a bounded research protocol and fake implementation.
3. Add `Draft`, `CriticResult`, and `DraftState` to `personalize_graph.py`.
4. Add pure local critic helpers before provider-based critique.
5. Add versioned prompt files.
6. Build the LangGraph graph and explicit node functions.
7. Add spend reservation and failure handling.
8. Add save/draft persistence and state-machine integration.
9. Add the `personalize` ARQ worker entry point.
10. Write focused personalization tests with fake LLM and research providers.
11. Run the focused Module 10 suite.
12. Run the full backend suite and confirm Modules 1-9 remain green.
13. Update `PROGRESS.md` and `README.md`.

## Acceptance checklist

- [x] `LLMClient` is behind a protocol and Groq's OpenAI-compatible adapter is separate.
- [x] `ResearchClient` is fakeable and bounded.
- [x] `Draft` Pydantic validation enforces subject and body limits.
- [x] The local critic rejects claims absent from research context.
- [x] The critic rejects spam language, fake familiarity, and unsupported CTAs.
- [x] The graph retries at most 2 times after critic failure.
- [x] Final rejection creates no send-ready draft or queue state.
- [x] LLM calls reserve spend atomically before provider work.
- [x] A spend cap hit pauses only personalization.
- [x] Approved drafts call `transition()` and become `drafted`.
- [x] `require_approval=true` does not enqueue the enrollment.
- [x] Footer text and opt-out links are absent from LLM output.
- [x] Reruns are idempotent.
- [x] Tests use fake LLM, fake research, fake ledger, and never touch the network.
- [x] Full test suite passes.
- [x] `PROGRESS.md` marks Module 10 done and points to Module 11.

## Risks to watch

- **Invented claims:** a provider draft and provider critique are not enough. Keep
  the local claim/context check as the final safety gate.
- **Prompt injection:** Treat researched web text as untrusted context, never as
  instructions. Prompt templates must isolate context.
- **Provider schema drift:** Parse and validate every provider response; reject
  malformed JSON instead of continuing.
- **Retry spend:** Every retry is a paid call and must reserve LLM spend separately.
- **Direct status writes:** Enrollments must change status only through
  `state_machine.transition()`.
- **Footers:** Keep compliance footer construction in `build_footer()` and
  `build_message()`; do not let prompts emit them.
- **Secrets in prompts/logs:** Never include API keys, Fernet values, email bodies,
  or full provider responses in logs or support bundles.
