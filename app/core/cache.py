
import json
import logging
from typing import Any

from redis.exceptions import RedisError

from app.core.redis import redis_manager

logger = logging.getLogger(__name__)

DEFAULT_TTL = 600


def get_redis():
    """Get the currently available Redis client."""
    return redis_manager.get_client()


async def get_cache(key: str) -> Any | None:
    """Retrieve and deserialize cached data."""

    client = get_redis()

    if client is None:
        return None

    try:
        value = await client.get(key)

        if value is None:
            return None

        return json.loads(value)

    except (RedisError, json.JSONDecodeError, TypeError):
        logger.exception("Redis cache read failed: %s", key)
        return None


async def set_cache(
    key: str,
    value: Any,
    ttl: int = DEFAULT_TTL,
) -> bool:
    """Serialize and store data with expiration."""

    client = get_redis()

    if client is None:
        return False

    try:
        serialized_value = json.dumps(
            value,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        await client.set(key, serialized_value, ex=ttl)

        return True

    except (RedisError, TypeError, ValueError):
        logger.exception("Redis cache write failed: %s", key)
        return False


async def delete_cache(key: str) -> bool:
    """Delete one cache key."""

    client = get_redis()

    if client is None:
        return False

    try:
        await client.delete(key)
        return True

    except RedisError:
        logger.exception("Redis cache deletion failed: %s", key)
        return False


async def delete_cache_pattern(pattern: str) -> int:
    """Delete matching keys using SCAN instead of KEYS."""

    client = get_redis()

    if client is None:
        return 0

    deleted_count = 0

    try:
        async for key in client.scan_iter(
            match=pattern,
            count=100,
        ):
            deleted_count += await client.delete(key)

    except RedisError:
        logger.exception(
            "Redis cache invalidation failed: %s",
            pattern,
        )

    return deleted_count
