
import logging

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self):
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        """Create Redis connection pool and verify connectivity."""

        if self.client is not None:
            return

        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            max_connections=50,
        )

        try:
            await client.ping()
        except RedisError:
            await client.aclose()
            logger.exception("Redis connection failed")
            self.client = None
            return

        self.client = client
        logger.info("Redis connected successfully")

    async def disconnect(self) -> None:
        """Close Redis connection pool."""

        if self.client is not None:
            await self.client.aclose()
            self.client = None
            logger.info("Redis disconnected")

    def get_client(self) -> redis.Redis | None:
        """Return the client, or None when Redis is unavailable."""

        return self.client


redis_manager = RedisManager()
