# LeadGen Agent — Beginner-Friendly Explanation

Reference notes for `leadgen-system-design-v2.md`. Read this first when you come back to the project.

## 1. What problem does it solve?

A business wants new customers by sending **cold emails** to people who have never heard of them. Doing that by hand breaks down fast:

- Where do you get hundreds of leads?
- Half the email addresses are dead — sending to them destroys your reputation.
- Writing 500 personal-sounding emails is impossible manually.
- Send too fast and Gmail/Outlook starts marking you as spam.
- Someone replies "stop" — if you email them again, you're breaking the law.
- Nobody tracks which message actually got meetings.

This app is a **machine that runs that whole process safely**, with a human approving the output and able to stop it at any moment. You don't run it as a shared website for many customers — you **sell a private copy to each business**, running on their own server with their own email accounts, their own AI key, and their own data. That's the key business decision: their data never touches another client's, and you have almost no running costs.

## 2. The complete workflow

Think of it as an **assembly line** where every lead moves through stations:

```
setup -> find leads -> score -> verify email -> write draft -> approve -> send -> watch inbox -> learn
```

**Setup (once per client):** admin account, license key, AI key, sender name + postal address (legally required in the footer), domain with SPF/DKIM/DMARC configured, mailboxes connected, daily sending limits, warm-up started. The tool refuses to send until this is complete.

**Per lead:**

1. **Source** — leads arrive from a CSV the client already owns, a crawler of public company websites, or optionally Apollo/Apify using *the client's own account*.
2. **Score** — how well does this person match the ideal customer profile?
3. **Verify** — is the email real? Syntax -> domain has mail servers (MX) -> not a disposable/role address -> paid verification API. Only `valid` addresses proceed.
4. **Personalize** — an AI agent researches the company website, picks an angle, writes a draft with a strict schema, then a **critic** step checks every factual claim against the research and rejects anything invented. Max 2 retries.
5. **Approve** — by default the client must approve drafts (mandatory for the first 50 emails).
6. **Send** — a background job every minute picks due emails and runs a gauntlet of checks: kill switch -> is it suppressed? -> license valid? -> inside the allowed send window? -> under the mailbox's daily cap? Only then does it send.
7. **Watch the inbox** — every few minutes it reads the mailboxes: bounces suppress the address, replies stop the sequence, "unsubscribe" suppresses permanently, out-of-office pauses.
8. **Optimize** — nightly stats, A/B testing of subject/opener/CTA, queue reordering toward leads that look like past winners, weekly report with cost per positive reply.

Follow-ups (step 1 -> 2 -> 3) are just the sequence continuing, with proper email threading so it looks like one conversation.

## 3. What each technology does

| Tech | Plain-English job |
|---|---|
| **FastAPI** | The backend web server. Receives requests from the dashboard, enforces permissions, talks to the database. |
| **Pydantic** | Defines exactly what data is allowed in and out. Also used to force the AI to return a predictable shape (subject, body, claims) instead of free text. |
| **SQLModel + SQLAlchemy** | Python classes that map to database tables. Async version so the server isn't blocked waiting. |
| **Postgres** | The permanent memory: leads, campaigns, sent messages, suppression list, spend ledger. |
| **Redis** | Fast temporary memory: the job queue, daily send counters (a counter that must be atomic), locks, logout blacklist. |
| **ARQ** | The background worker system. "Do this job later / every minute" — separate from the web server so slow work never freezes the UI. |
| **LangGraph** | Orchestrates the AI agent as a graph of steps (research -> draft -> critic -> retry) instead of one giant prompt. |
| **LLM client** | Talks to any OpenAI-compatible provider (default Groq) using the client's key. |
| **React** | The dashboard in the browser: campaigns, approval queue, inbox, analytics. |
| **SMTP / IMAP** | The universal email protocols — send via SMTP, read via IMAP. Works with any provider, avoids Google's expensive OAuth audit. |
| **Caddy** | Puts HTTPS in front of everything with almost no config. |
| **Docker Compose** | Packages all six services (caddy, web, api, worker, postgres, redis) so install is one command. |
| **Alembic** | Database migrations — upgrades the table structure on an existing install during updates. |

## 4. How the parts communicate

Two rules explain almost everything:

**Rule A — the browser never touches the database.** React calls FastAPI over HTTPS (`/api/...`) with a JWT login token. FastAPI checks the token, reads/writes Postgres, and returns JSON. Caddy sits in front and routes `/` to the static React build and `/api` to FastAPI.

**Rule B — the web server and worker never call each other.** They cooperate **through the database and the queue**, like two coworkers sharing a whiteboard:

```
React -> Caddy -> FastAPI -> Postgres   (user actions, form submissions)
                   |
              Redis/ARQ queue             ("please verify this email", "personalize this lead")
                   |
                Worker  -> Postgres        (updates status, records results)
                   |
        SMTP/IMAP, LLM, verifier APIs      (external world)
```

The worker is a separate container running the *same image*, just a different command. If the worker crashes, the website keeps working; if the website restarts, queued jobs survive in Redis. The AI agent is not a separate service — it's just a module the worker calls, behind an `LLMClient` interface so it can be swapped or faked in tests.

**Interfaces matter here:** `LeadSource`, `Verifier`, `MailProvider`, `LLMClient`. Each is a defined contract with a fake version for tests. This is what lets you test the entire pipeline without sending a single real email or spending a cent.

## 5. The hardest engineering components

1. **The send engine under concurrency.** `send_due` can run in multiple worker instances. Two workers grabbing the same lead = double email = destroyed reputation. The fix is `SELECT ... FOR UPDATE SKIP LOCKED` plus an idempotent design. This is the single most dangerous piece of code in the project.
2. **The Redis daily-cap limiter.** Must be atomic. Check-then-increment races and lets you exceed the cap. The `INCR`, check, `DECR`-if-over pattern in Section 13 is small but subtle.
3. **State machine discipline.** Status changes only through one function, and illegal transitions raise. Without this, a replied lead can accidentally get step 3. It's boring code that prevents catastrophic bugs.
4. **Deliverability and compliance.** SPF/DKIM/DMARC checks, warm-up ramps, jitter/pacing, bounce-rate auto-pause, mandatory footer, suppression that is *always* re-checked before every send, country rules. Mostly logic and policy, not clever algorithms — and the place where a bug is a legal problem.
5. **Inbox correlation.** Matching a reply to the right enrollment via `In-Reply-To`/`References` headers, plus parsing bounces (DSN codes) which every provider formats slightly differently. Messy real-world data.
6. **AI reliability.** The model will invent "I loved your recent funding round." The critic node comparing `claims` against fetched `context` is the actual product value; without it the tool produces embarrassing mail.
7. **Packaging.** Installer, migrations on start, health checks, update with rollback, backup + restore, support bundle. Unglamorous but it's what makes the thing *sellable*.
8. **Soft licensing.** Must block new campaigns on expiry while *never* blocking unsubscribes or bounce handling. Easy to get backwards.

## 6. What to build first, and why

Follow the order in Section 22 — it's deliberately arranged so each layer is testable before the next exists:

**Start with: models/migrations (1) -> state machine (2) -> limiter (3) -> suppression (4) -> `send_due` with a FakeMailProvider (5).**

Reasoning:

- **Data model first** because every other module refers to it. Getting tables wrong later means painful migrations.
- **State machine + limiter + suppression are pure logic** — no network, no AI, no UI. You can test them completely and they are exactly where the "silent skip a check" bugs live. Section 0 explicitly tells you to read these line by line yourself.
- **`send_due` early** because it's the risky heart of the system. Building it while using a **fake mail provider** means you can prove: two workers never double-send, suppressed emails never go out, caps are never exceeded, transient failures back off. Those are the guarantees the product is sold on.
- This gives you a **walking skeleton**: database -> state -> queue -> send loop, fully tested, with no real email leaving the machine.

**Deliberately last:** the React dashboard and the LangGraph agent. The UI is easy once the API is stable, and rebuilding screens because the API changed is wasted work. The AI agent is the most *fun* part and the biggest temptation — but without verification and the safe send path, drafts don't matter yet. If you start with the agent, you'll build a demo that can't safely send anything.

**One extra tip for learning with a coding agent:** give it one module per session, ask for the tests *with* the code, then read the send/limiter/state-machine/license code yourself before committing. The agent writes plausible code — plausible is exactly the failure mode you can't detect by running it once.
