from datetime import date
from typing import Protocol


CAP_TTL_SECONDS = 60 * 60 * 30


class RedisLike(Protocol):
    async def incr(self, key: str) -> int: ...

    async def decr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> bool: ...


def cap_key(mailbox_id, day: date) -> str:
    return f"cap:{mailbox_id}:{day:%Y%m%d}"


async def try_acquire(
    redis: RedisLike,
    mailbox_id,
    cap: int,
    day: date,
) -> bool:
    if cap <= 0:
        return False

    key = cap_key(mailbox_id, day)
    count = await redis.incr(key)

    if count == 1:
        await redis.expire(key, CAP_TTL_SECONDS)

    if count > cap:
        await redis.decr(key)
        return False

    return True


async def release(redis: RedisLike, mailbox_id, day: date) -> None:
    """Release one send slot; callers must call this exactly once per acquired slot."""
    await redis.decr(cap_key(mailbox_id, day))
