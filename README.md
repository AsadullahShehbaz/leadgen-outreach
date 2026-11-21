# LeadGen

**Automated B2B cold outreach that finds prospects, writes personalized emails, and protects your reputation — with a human always in control.**

LeadGen automates the B2B outreach workflow, from prospect discovery and verification to AI-powered personalization, email delivery, and performance analytics.

---

## The Problem

Cold email works, but managing it manually becomes difficult at scale:

- Finding hundreds of relevant prospects takes hours.
- Invalid email addresses damage domain reputation.
- Writing personalized emails manually is time-consuming.
- Sending too quickly increases spam risks.
- Contacting someone who unsubscribed creates compliance problems.
- Tracking which campaigns generate actual business results is difficult.

LeadGen automates this process while keeping humans in control.

## How It Works

Every prospect moves through the following workflow:

1. **Find** — Import CSV files, discover prospects through public company websites, or integrate with Apollo and Apify.
2. **Score** — Evaluate prospects against your Ideal Customer Profile (ICP).
3. **Verify** — Check email syntax, mail servers, disposable addresses, role-based addresses, and verification API results.
4. **Personalize** — AI researches companies and generates personalized email drafts. A separate critic checks factual claims.
5. **Approve** — Review and approve generated drafts before sending. Approval is mandatory for the first 50 emails.
6. **Send** — Emails pass through safety checks, suppression rules, sending windows, and daily mailbox limits.
7. **Watch** — Process bounces, replies, unsubscribes, and out-of-office responses automatically.
8. **Learn** — Use A/B testing, campaign optimization, and weekly performance reports to improve results.

## Safety Is the Product

| Protection | What It Does |
|---|---|
| Email verification | Filters invalid, disposable, and risky email addresses. |
| Permanent suppression | Prevents contacting unsubscribed, bounced, or complaining recipients again. |
| Human approval | Keeps humans involved in reviewing and approving email drafts. |
| Deliverability gates | Requires SPF, DKIM, and DMARC checks before sending. |
| Sending limits | Controls daily sending volume and gradually ramps up campaigns. |
| Automatic brakes | Pauses sending when hard bounces or spam complaints increase. |
| Honest personalization | Rejects unsupported or fabricated claims about prospects. |
| Compliance controls | Supports sender identification, postal addresses, opt-out links, and lawful-basis records. |
| Spend protection | Provides daily usage limits for AI, verification, and prospect-source credits. |
| Independent safety controls | Keeps unsubscribe and bounce handling operational even when other application services are unavailable. |

## What LeadGen Never Does

- Never emails someone who has unsubscribed or bounced.
- Never replies to a prospect automatically.
- Never uses open-tracking pixels.
- Never invents personal facts about a prospect.
- Never bypasses mandatory safety checks.
- Never allows sending limits to be ignored.
- Never disables unsubscribe or bounce handling because of unrelated application failures.

## Results You Can Measure

LeadGen focuses on meaningful business metrics:

- Positive replies.
- Meetings generated.
- Customers won per 1,000 leads.
- Cost per positive reply.
- Campaign performance.
- Email bounce and complaint rates.

The focus is on actual business outcomes rather than email opens.

## Who Is It For?

LeadGen is designed for:

- B2B sales teams.
- Marketing agencies.
- Lead generation agencies.
- Startups and small businesses.
- Businesses looking to automate prospect research and cold email campaigns.

It works best for businesses with a clear offer, relevant prospect lists, and a commitment to email deliverability best practices.

## Under the Hood

| Technology | Purpose |
|---|---|
| **FastAPI + PostgreSQL** | Backend API and persistent data storage. |
| **Redis + ARQ** | Background job processing and atomic daily sending limits. |
| **LangGraph + OpenAI-compatible LLMs** | AI-powered research, email generation, and claim verification. |
| **SMTP / IMAP** | Email sending and inbox monitoring. |
| **React** | Frontend dashboard and campaign management. |
| **Docker Compose + Caddy** | Application containerization and automatic HTTPS. |
| **Alembic** | Database schema migrations. |

Tests use mock providers and do not send real emails or make external network requests.

## Project Status

LeadGen is currently in active development.

- **Completed:** Environment setup, complete data layer with 16 database tables, Alembic migrations, passing unit tests, the enrollment state machine, the Redis daily limiter with timezone-aware send windows, suppression/compliance helpers, `send_due` with a FakeMailProvider, the inbox worker, authentication/setup APIs, spend caps with usage ledger, source/verification pipelines with fakes, the LangGraph personalization agent using Groq's OpenAI-compatible API, and offline Ed25519 license enforcement.
- **Next:** Packaging.
- **Planned:** Dashboard and campaign optimizer.

See [PROGRESS.md](PROGRESS.md) for the development tracker.

## Documentation

- [System Design](docs/leadgen-system-design-v2.md) — Complete product and engineering specification.
- [Beginner-Friendly Explanation](docs/leadgen-explained-for-beginners.md) — Understand the entire system in simple language.
- [Module 1 Tutorial](docs/tutorials/module1.md) — Learn how the database layer was built and why each table exists.
- [Module 4 Plan](docs/plan/module-04-suppression-compliance.md) — Implemented suppression and compliance helpers.
- [Module 8 Plan](docs/plan/module-08-spend-caps-ledger.md) — Implemented spend caps and usage ledger.
- [Module 9 Plan](docs/plan/module-09-sources-verifier.md) — Implemented lead sourcing and verification pipeline.
- [Module 10 Plan](docs/plan/module-10-langgraph-agent.md) — Implemented LangGraph personalization with a factual critic.
- [Module 12 Plan](docs/plan/module-12-packaging.md) — Docker, deployment, backup, update, rollback, and support packaging plan.

## Important Disclaimer

LeadGen is an automation tool, not a guarantee of sales or deliverability. Results depend on domain reputation, prospect list quality, email content, and the relevance of the business offer.

The system prioritizes responsible outreach, deliverability, and human oversight throughout the process.
