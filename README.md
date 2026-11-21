# LeadGen

**Automated B2B cold outreach that finds prospects, writes personalized emails, and protects your reputation — with a human always in control.**

Every client gets a private deployment on their own server, with their own email accounts, their own data provider, and their own AI key. No shared data. No shared credentials. No telemetry.

---

## The problem

Cold email works, but doing it by hand breaks down fast:

- Finding hundreds of relevant prospects takes hours.
- Half the addresses are dead — and sending to them damages your domain.
- Writing 500 personal-sounding emails is impossible manually.
- Sending too fast gets you marked as spam.
- One email to someone who said "stop" is a legal problem.
- Nobody knows which messages actually won meetings.

LeadGen runs that entire process safely, and stops instantly when a human says stop.

## How it works

Every prospect moves down one assembly line:

1. **Find** — import a CSV you own, crawl public company websites, or connect Apollo/Apify with your own account.
2. **Score** — measure each person against your ideal customer profile.
3. **Verify** — syntax, mail servers, disposable and role-address filters, then a paid verification API. Only valid addresses move forward; risky ones at a capped share.
4. **Personalize** — AI researches the company and drafts the email. A separate critic checks every factual claim and rejects anything invented.
5. **Approve** — you review and approve drafts. Approval is mandatory for the first 50 emails.
6. **Send** — every email passes a gauntlet of checks: kill switch, suppression, license, send window, and daily mailbox cap. Once a minute.
7. **Watch** — bounces suppress the address; replies stop the sequence; "unsubscribe" is permanent; out-of-office pauses until the person returns.
8. **Learn** — A/B tests, queue reordering toward leads that look like past winners, and a weekly report with cost per positive reply.

## Safety is the product

| Protection | What it does |
| --- | --- |
| Verified before contact | Only valid addresses are emailed. Dead and role addresses never reach the send queue. |
| Permanent suppression | Unsubscribes, bounces, and complaints are suppressed forever and re-checked before every single send. |
| Human approval | Drafts wait for a human by default and are mandatory for the first 50 emails. |
| Deliverability gates | No sending until SPF, DKIM, and DMARC pass. Warm-up ramps and a 30–50 emails per mailbox per day target. |
| Automatic brakes | A spike in hard bounces or spam complaints pauses the mailbox before damage spreads. |
| Honest personalization | Invented facts are rejected by a critic step, so no embarrassing "I loved your funding round" emails. |
| Built-in compliance | Sender identity, postal address, and opt-out in every footer; a lawful-basis record per lead; Germany and Canada blocked by default without one. |
| Spend protection | Daily caps for AI, verification, and source credits — no surprise bills. |
| License that never harms compliance | An expired license can pause new campaigns, but never unsubscribes, suppression, or bounce handling. |

## What LeadGen never does

- Never emails someone who unsubscribed or bounced.
- Never replies to a prospect automatically.
- Never uses open-tracking pixels.
- Never invents personal facts about a prospect.
- Never puts one client's data or credentials inside another client's deployment.
- Never lets a billing or license problem disable unsubscribes or bounce handling.

## Results you can measure

LeadGen tracks what matters to a business: **positive replies, meetings, customers won per 1,000 leads, and cost per positive reply.** Not opens.

## Sold as a private copy, not a shared website

| Delivery | Who runs it |
| --- | --- |
| Self-host | The client's own IT team |
| Done-for-you install | Installed on the client's server, then handed over |
| Managed dedicated instance | One private instance hosted for that client |

The client is always the legal sender, owns their accounts, and keeps their data. The seller keeps near-zero running costs.

## Who it is for

B2B teams, agencies, and small businesses with a clear offer — and the discipline to follow deliverability best practices. Cold email is not a magic button: results depend on domain reputation, list quality, and the offer itself.

## Under the hood

- **FastAPI + Postgres** — API and permanent memory.
- **Redis + ARQ** — job queue and atomic daily send caps.
- **LangGraph + any OpenAI-compatible LLM** — research, drafting, and the claim-checking critic.
- **SMTP/IMAP** — works with any email provider.
- **React** — the dashboard.
- **Docker Compose + Caddy** — one-command install and automatic HTTPS.

Tests use fake providers and never touch the network or send a real email.

## Project status

LeadGen is in active development.

- **Done:** environment, complete data layer — 16 tables, an Alembic migration, and passing unit tests — plus the enrollment state machine with tests for every allowed and illegal transition.
- **Next:** the rest of the safety-critical core — limiter, suppression, and the send engine.
- **Later:** inbox worker, authentication and setup wizard, lead sources and verification, AI agent, licensing, packaging, dashboard, and optimizer.

See [PROGRESS.md](PROGRESS.md) for the live module tracker.

## Documentation

- [System design](docs/leadgen-system-design-v2.md) — the full product and engineering specification.
- [Beginner-friendly explanation](docs/leadgen-explained-for-beginners.md) — the whole system in plain English.
- [Module 1 tutorial](docs/tutorials/module1.md) — how the data layer was built and why every table exists.

## The honest fine print

LeadGen is a tool, not a guarantee. Deliverability and results depend on the client's domains, list quality, and offer. Every deployment starts with a human in the loop, and the product is designed so the safest path is also the default path.
