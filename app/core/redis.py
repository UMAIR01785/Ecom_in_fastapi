
import logging

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self):
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        """Initialize Redis connection pool."""

        self.client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
            max_connections=50,
        )

        try:
            await self.client.ping()
            logger.info("Redis connected successfully")

        except RedisError as exc:
            logger.warning("Redis is unavailable: %s", exc)

    async def disconnect(self) -> None:
        """Close Redis connection pool."""

        if self.client is not None:
            await self.client.aclose()
            self.client = None
            logger.info("Redis connection closed")

    def get_client(self) -> redis.Redis:
        """Return initialized Redis client."""

        if self.client is None:
            raise RuntimeError("Redis has not been initialized")

        return self.client


redis_manager = RedisManager()
