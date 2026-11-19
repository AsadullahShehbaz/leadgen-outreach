# LeadGen Agent (sold as dedicated deployments)

Stack: FastAPI (async), SQLModel, Postgres, ARQ + Redis, LangGraph + OpenAI-compatible LLM, React, Docker Compose, Caddy.

Read docs/leadgen-system-design-v2.md before any task.

## Architecture rules

- Routers in app/routers, Pydantic schemas in app/schemas, tables in app/models.
- Client-owned credentials only. No shared keys, no telemetry by default.
- External services only behind interfaces: LeadSource, Verifier, MailProvider, LLMClient.
- Status changes ONLY via services/sequencing/state_machine.py.
- All jobs idempotent. send_due order: kill switch -> SKIP LOCKED -> suppression -> license -> window -> Redis cap -> send.
- License problems may block sourcing and new sends but NEVER unsubscribes, suppression or bounce handling.
- No open-tracking pixels. No auto-reply to prospects.
- Follow the existing architecture. Do not introduce new patterns, libraries or layers without asking first.

## Security and safety

- Secrets from env vars or encrypted columns only. Never log secrets or email bodies.
- Never expose API keys or secrets in code, logs, test fixtures, error messages or support bundles.
- Never use real email accounts during testing. Tests use Fake providers and never touch the network or send real email.
- Ask before destructive operations (dropping data, deleting files, resetting databases, force-pushing, rewriting history).

## Code quality

- Every piece of code must be beginner friendly, easy and simple. Do not overkill or overengineer if simple code works and solves the problem (Quote: Less is always more).
- Write beginner-friendly code comments where useful.
- Explain important implementation decisions.
- Never invent missing requirements. If something is unclear or absent from the design doc, ask instead of guessing.
- Write tests for every important feature. At minimum: pytest tests for state machine, limiter, suppression, bounce parser, license, spend caps.
