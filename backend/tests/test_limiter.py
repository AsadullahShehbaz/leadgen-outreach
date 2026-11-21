import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest

from app.services.sequencing.limiter import (
    CAP_TTL_SECONDS,
    cap_key,
    release,
    try_acquire,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.lock = asyncio.Lock()

    async def incr(self, key: str) -> int:
        async with self.lock:
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key]

    async def decr(self, key: str) -> int:
        async with self.lock:
            self.values[key] = self.values.get(key, 0) - 1
            if self.values[key] <= 0:
                self.values.pop(key, None)
                self.ttls.pop(key, None)
                return 0
            return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        async with self.lock:
            self.ttls[key] = seconds
            return True


DAY = date(2026, 11, 23)


async def test_first_acquire_creates_key_and_ttl():
    redis = FakeRedis()
    assert await try_acquire(redis, "mailbox-a", 10, DAY)

    key = cap_key("mailbox-a", DAY)
    assert redis.values[key] == 1
    assert redis.ttls[key] == CAP_TTL_SECONDS


async def test_exact_cap_and_counter_after_overflow():
    redis = FakeRedis()
    mailbox = "mailbox-a"

    for _ in range(3):
        assert await try_acquire(redis, mailbox, 3, DAY)
    assert not await try_acquire(redis, mailbox, 3, DAY)
    assert redis.values[cap_key(mailbox, DAY)] == 3


async def test_mailboxes_and_days_are_independent():
    redis = FakeRedis()
    assert await try_acquire(redis, "a", 1, DAY)
    assert not await try_acquire(redis, "a", 1, DAY)
    assert await try_acquire(redis, "b", 1, DAY)
    assert await try_acquire(redis, "a", 1, date(2026, 11, 24))


async def test_zero_or_negative_cap_never_touches_redis():
    redis = FakeRedis()
    assert not await try_acquire(redis, "a", 0, DAY)
    assert not await try_acquire(redis, "a", -2, DAY)
    assert redis.values == {}


async def test_release_frees_a_slot():
    redis = FakeRedis()
    assert await try_acquire(redis, "a", 1, DAY)
    assert not await try_acquire(redis, "a", 1, DAY)

    await release(redis, "a", DAY)
    assert await try_acquire(redis, "a", 1, DAY)


async def test_200_concurrent_acquires_never_exceed_cap():
    redis = FakeRedis()
    results = await asyncio.gather(
        *(try_acquire(redis, "a", 10, DAY) for _ in range(200))
    )

    assert sum(results) == 10
    assert redis.values[cap_key("a", DAY)] == 10


async def test_three_mailboxes_have_independent_concurrency_limits():
    redis = FakeRedis()
    tasks = [
        try_acquire(redis, mailbox, 5, DAY)
        for mailbox in ("a", "b", "c")
        for _ in range(50)
    ]
    results = await asyncio.gather(*tasks)

    assert sum(results[:50]) == 5
    assert sum(results[50:100]) == 5
    assert sum(results[100:]) == 5
    for mailbox in ("a", "b", "c"):
        assert redis.values[cap_key(mailbox, DAY)] == 5


@pytest.mark.integration
async def test_real_redis_concurrent_acquires():
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not configured")

    from redis.asyncio import Redis

    redis = Redis.from_url(redis_url)
    mailbox = str(uuid4())
    key = cap_key(mailbox, DAY)

    try:
        await redis.delete(key)
        results = await asyncio.gather(
            *(try_acquire(redis, mailbox, 10, DAY) for _ in range(200))
        )
        assert sum(results) == 10
    finally:
        await redis.delete(key)
        await redis.aclose()
