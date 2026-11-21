from redis.asyncio import Redis


def get_redis(url: str) -> Redis:
    """Create a Redis client. Callers own and close it when appropriate."""
    return Redis.from_url(url, decode_responses=True)
