import json
import logging
from typing import Any

from app.core.redis import redis_client

logger = logging.getLogger(__name__)


async def get_cache(key: str) -> Any | None:
    """Retrieve and deserialize a cached value."""
    try:
        value = await redis_client.get(key)

        if value is None:
            return None

        return json.loads(value)

    except Exception:
        logger.exception("Redis cache read failed for key: %s", key)
        return None


async def set_cache(
    key: str,
    value: Any,
    ttl: int = 600,
) -> bool:
    """Serialize and store a value in Redis."""
    try:
        serialized_value = json.dumps(value)

        await redis_client.set(
            key,
            serialized_value,
            ex=ttl,
        )

        return True

    except Exception:
        logger.exception("Redis cache write failed for key: %s", key)
        return False


async def delete_cache(key: str) -> bool:
    """Delete a cache key."""
    try:
        await redis_client.delete(key)
        return True

    except Exception:
        logger.exception("Redis cache deletion failed for key: %s", key)
        return False


async def delete_cache_pattern(pattern: str) -> int:
    """Delete cache keys matching a pattern without blocking Redis."""
    deleted_count = 0

    try:
        async for key in redis_client.scan_iter(
            match=pattern,
            count=100,
        ):
            deleted_count += await redis_client.delete(key)

        return deleted_count

    except Exception:
        logger.exception(
            "Redis pattern invalidation failed: %s",
            pattern,
        )
        return deleted_count