# Real Async Redis Client Plan

Status: planned.
Design reference: `docs/leadgen-system-design-v2.md`, Sections 4, 5, 7.3, 13 and 22.
Tutorial template: connect with `redis.asyncio`, keep connection settings in environment
configuration, await Redis operations, and verify behavior against a running Redis server.

## Goal

Use a real asynchronous Redis client in application and worker runtime paths, starting
with the daily send-cap limiter. Keep Redis operations non-blocking and make Redis
availability mandatory for operations that rely on Redis safety checks.

No token blacklist, logout endpoint, or unrelated Redis feature is included in this work.

## Current state

- `app/services/sequencing/limiter.py` accepts a small async `RedisLike` protocol but
  does not create or obtain a production client.
- `tests/test_limiter.py` uses `FakeRedis` for unit tests and has an opt-in real-Redis
  concurrency test.
- `app/core/config.py` currently has `REDIS_HOST` and `REDIS_PORT`; the system design
  specifies `REDIS_URL`. The example environment file currently documents only
  `TEST_REDIS_URL`.
- `app/main.py` has no Redis lifecycle management. An ARQ settings module and production
  worker call sites are not present yet.

`FakeRedis` is a test double, not a production Redis implementation. Retain it for
network-free unit tests.

## Decisions

| Topic | Decision |
|---|---|
| Client | Use the existing `redis` dependency's `redis.asyncio` client. |
| Connection configuration | Align runtime configuration with the design's `REDIS_URL`; keep a separate test-only Redis URL. |
| Client ownership | Create and close the client at the owning app or worker lifecycle boundary; do not create a client per operation. |
| Error behavior | Redis errors must be visible and must not silently bypass a Redis-backed safety check or switch to a fake. |
| Tests | Keep unit tests on `FakeRedis`; run real-Redis tests only with an explicitly configured test URL and isolated keys. |

## Deliverables

```text
backend/
  app/core/config.py             # Redis URL setting and test URL
  app/core/redis.py              # NEW: async client construction and small helpers
  app/main.py                    # FastAPI startup/shutdown client lifecycle
  app/workers/arq_settings.py    # NEW when worker runtime is introduced; ARQ lifecycle
  app/services/sequencing/limiter.py
                                 # Keep the existing RedisLike interface and limiter behavior
  tests/test_config.py           # Redis settings coverage
  tests/test_limiter.py          # Fake unit tests plus isolated real-Redis integration
  .env.example                   # Runtime and test Redis configuration
```

Only add or update worker call sites that exist when implementation begins. When
`send_due` is added, pass the worker-owned real client as `ctx["redis"]`, preserving the
design's required send-check order.

## Implementation

1. **Configuration**
   - Add the runtime `REDIS_URL` setting, consistent with Section 7.3 of the design.
   - Keep `TEST_REDIS_URL` separate so integration tests cannot accidentally use the
     runtime database.
   - Update `.env.example` with local development examples and a clear test-only note.
   - Remove the old host/port settings only after checking and updating all consumers.

2. **Async client module**
   - Add a small `app/core/redis.py` module using `Redis.from_url(...)`.
   - Provide the application/worker client through lifecycle setup rather than opening
     a new connection for each operation.
   - Expose only small helpers needed by current Redis operations; avoid duplicating
     limiter logic in this module.

3. **Application and worker lifecycle**
   - Create the client when FastAPI starts and close it on shutdown.
   - Add equivalent startup/shutdown ownership for the ARQ worker when its settings
     module is introduced.
   - Make Redis readiness explicit in health reporting without turning Redis failures
     into successful responses.

4. **Wire runtime operations**
   - Pass the real async client to the existing limiter functions at production call
     sites.
   - Await each Redis operation and preserve the design's send order: kill switch,
     `SKIP LOCKED`, suppression, license, send window, Redis cap, then send.
   - If Redis is unavailable, do not send without the required cap check.

5. **Tests and validation**
   - Keep unit tests using `FakeRedis`; preserve checks for caps, TTL, release behavior,
     and concurrency.
   - Add configuration and client-lifecycle tests that do not require a live Redis
     server where feasible.
   - Use `TEST_REDIS_URL` for the real-Redis concurrency test. Keep test keys isolated
     and delete only keys created by that test.
   - Verify connection failure is surfaced and cannot lead to an unchecked send.
   - Run the focused config and limiter tests, then the backend test suite.

## Acceptance checklist

- [ ] Production runtime paths use `redis.asyncio`, not a fake or no-op client.
- [ ] Application and worker clients are reused and closed at shutdown.
- [ ] Redis configuration is documented and consistent with the system design.
- [ ] Redis-backed send safety checks fail closed when Redis is unavailable.
- [ ] Existing `FakeRedis` unit tests remain network-free and pass.
- [ ] Real-Redis concurrency test proves the configured cap is not exceeded.
- [ ] No Redis URL, password, or other credential is logged or committed.

## Risks to watch

- **Configuration drift:** the current code uses host/port fields while the design
  specifies `REDIS_URL`. Update every consumer together and keep test Redis separate.
- **Unwired worker:** the limiter can be tested independently but has no production
  send caller yet. Ensure the real client is passed when ARQ and `send_due` are built.
- **Lifecycle leaks:** one client per request/job can exhaust connections. Keep ownership
  at app/worker lifecycle scope and close it explicitly.
- **Fail-open behavior:** a Redis exception must never cause sends to proceed without
  the daily cap check.
- **Test data:** integration tests should use a dedicated test Redis database and
  unique keys; never flush a shared Redis instance.
