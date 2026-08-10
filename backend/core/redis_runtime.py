import inspect
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import redis
import redis.asyncio as aioredis

from backend.config import (
    REDIS_CONNECT_TIMEOUT_S,
    REDIS_HEALTH_CHECK_INTERVAL_S,
    REDIS_KEY_PREFIX,
    REDIS_MAX_CONNECTIONS,
    REDIS_SOCKET_TIMEOUT_S,
    REDIS_URL,
)

logger = logging.getLogger(__name__)


def _normalize_prefix(prefix: str) -> str:
    value = str(prefix or "").strip()
    if value and not value.endswith(":"):
        value += ":"
    return value


class RedisRuntime:
    """Process-local Redis connection/runtime boundary.

    One runtime owns the sync and async connection pools used by StateStore,
    EventBus, health checks, execution coordination, and WebSocket pub/sub.
    Redis remains an external dependency; this class never starts a Redis
    server process.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        key_prefix: str | None = None,
        max_connections: int | None = None,
        connect_timeout_s: float | None = None,
        socket_timeout_s: float | None = None,
        health_check_interval_s: int | None = None,
    ):
        self.redis_url = redis_url or REDIS_URL
        self.key_prefix = _normalize_prefix(
            REDIS_KEY_PREFIX if key_prefix is None else key_prefix
        )
        self.max_connections = max(
            1,
            int(REDIS_MAX_CONNECTIONS if max_connections is None else max_connections),
        )
        self.connect_timeout_s = max(
            0.1,
            float(
                REDIS_CONNECT_TIMEOUT_S
                if connect_timeout_s is None
                else connect_timeout_s
            ),
        )
        self.socket_timeout_s = max(
            0.1,
            float(
                REDIS_SOCKET_TIMEOUT_S
                if socket_timeout_s is None
                else socket_timeout_s
            ),
        )
        self.health_check_interval_s = max(
            0,
            int(
                REDIS_HEALTH_CHECK_INTERVAL_S
                if health_check_interval_s is None
                else health_check_interval_s
            ),
        )

        self._lock = threading.RLock()
        self._sync_pool: redis.ConnectionPool | None = None
        self._sync_client: redis.Redis | None = None
        self._async_pool: aioredis.ConnectionPool | None = None
        self._async_client: aioredis.Redis | None = None

        self._last_ping_monotonic = 0.0
        self._last_successful_ping: str | None = None
        self._last_ping_latency_ms: float | None = None
        self._last_error = ""
        self._connection_failures = 0
        self._reconnect_count = 0
        self._publish_failures = 0
        self._degraded = False

    def key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def channel(self, channel: str) -> str:
        return self.key(channel)

    def _connection_kwargs(self) -> dict[str, Any]:
        return {
            "decode_responses": True,
            "max_connections": self.max_connections,
            "socket_connect_timeout": self.connect_timeout_s,
            "socket_timeout": self.socket_timeout_s,
            "health_check_interval": self.health_check_interval_s,
            "socket_keepalive": True,
        }

    def _ensure_sync_client(self) -> redis.Redis:
        with self._lock:
            if self._sync_pool is None:
                self._sync_pool = redis.ConnectionPool.from_url(
                    self.redis_url,
                    **self._connection_kwargs(),
                )
            if self._sync_client is None:
                self._sync_client = redis.Redis(connection_pool=self._sync_pool)
            return self._sync_client

    def _should_ping(self) -> bool:
        if self.health_check_interval_s <= 0:
            return True
        return (
            time.monotonic() - self._last_ping_monotonic
            >= self.health_check_interval_s
        )

    def _record_success(self, latency_ms: float) -> None:
        with self._lock:
            if self._degraded:
                self._reconnect_count += 1
            self._degraded = False
            self._last_error = ""
            self._last_ping_monotonic = time.monotonic()
            self._last_successful_ping = datetime.now(timezone.utc).isoformat()
            self._last_ping_latency_ms = round(latency_ms, 2)

    def mark_failure(self, exc: Exception | str, *, reset: bool = False) -> None:
        with self._lock:
            self._connection_failures += 1
            self._degraded = True
            self._last_error = str(exc)
        if reset:
            self.reset_sync()

    def get_client(self, *, ping: bool = True) -> redis.Redis | None:
        try:
            client = self._ensure_sync_client()
            if ping and self._should_ping():
                started = time.monotonic()
                client.ping()
                self._record_success((time.monotonic() - started) * 1000)
            return client
        except Exception as exc:
            self.mark_failure(exc, reset=True)
            logger.warning("Redis unavailable at %s", self.redis_url)
            return None

    def ping(self) -> tuple[bool, float | None]:
        try:
            client = self._ensure_sync_client()
            started = time.monotonic()
            client.ping()
            latency_ms = (time.monotonic() - started) * 1000
            self._record_success(latency_ms)
            return True, round(latency_ms, 2)
        except Exception as exc:
            self.mark_failure(exc, reset=True)
            return False, None

    def publish(self, channel: str, payload: str) -> bool:
        client = self.get_client()
        if client is None:
            return False
        try:
            client.publish(self.channel(channel), payload)
            return True
        except Exception as exc:
            with self._lock:
                self._publish_failures += 1
            self.mark_failure(exc, reset=True)
            logger.warning("Failed to publish Redis event", exc_info=True)
            return False

    def get_async_client(self) -> aioredis.Redis:
        with self._lock:
            if self._async_pool is None:
                self._async_pool = aioredis.ConnectionPool.from_url(
                    self.redis_url,
                    **self._connection_kwargs(),
                )
            if self._async_client is None:
                self._async_client = aioredis.Redis(
                    connection_pool=self._async_pool
                )
            return self._async_client

    def create_async_pubsub(self):
        return self.get_async_client().pubsub()

    async def close_pubsub(self, pubsub, channel: str | None = None) -> None:
        if pubsub is None:
            return
        try:
            if channel:
                result = pubsub.unsubscribe(self.channel(channel))
                if inspect.isawaitable(result):
                    await result
        except Exception:
            logger.debug("Redis pubsub unsubscribe failed", exc_info=True)
        try:
            close_fn = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close_fn is not None:
                result = close_fn()
                if inspect.isawaitable(result):
                    await result
        except Exception:
            logger.debug("Redis pubsub close failed", exc_info=True)

    def reset_sync(self) -> None:
        with self._lock:
            pool = self._sync_pool
            self._sync_client = None
            self._sync_pool = None
            self._last_ping_monotonic = 0.0
        if pool is not None:
            try:
                pool.disconnect()
            except Exception:
                logger.debug("Redis sync pool disconnect failed", exc_info=True)

    async def reset_async(self) -> None:
        with self._lock:
            pool = self._async_pool
            self._async_client = None
            self._async_pool = None
        if pool is not None:
            try:
                result = pool.disconnect()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.debug("Redis async pool disconnect failed", exc_info=True)

    def health_snapshot(self) -> dict[str, Any]:
        with self._lock:
            sync_pool = self._sync_pool
            async_pool = self._async_pool
            in_use = len(getattr(sync_pool, "_in_use_connections", ()) or ())
            available = len(getattr(sync_pool, "_available_connections", ()) or ())
            async_in_use = len(
                getattr(async_pool, "_in_use_connections", ()) or ()
            )
            return {
                "connected": not self._degraded and self._last_successful_ping is not None,
                "last_successful_ping": self._last_successful_ping,
                "last_error": self._last_error,
                "ping_latency_ms": self._last_ping_latency_ms,
                "connection_failures": self._connection_failures,
                "reconnect_count": self._reconnect_count,
                "publish_failures": self._publish_failures,
                "key_prefix": self.key_prefix,
                "max_connections": self.max_connections,
                "sync_pool_created": sync_pool is not None,
                "sync_pool_in_use": in_use,
                "sync_pool_available": available,
                "async_pool_created": async_pool is not None,
                "async_pool_in_use": async_in_use,
                "degraded": self._degraded,
            }

    async def close(self) -> None:
        self.reset_sync()
        await self.reset_async()


_default_runtime: RedisRuntime | None = None
_default_runtime_lock = threading.Lock()


def get_redis_runtime() -> RedisRuntime:
    global _default_runtime
    if _default_runtime is None:
        with _default_runtime_lock:
            if _default_runtime is None:
                _default_runtime = RedisRuntime()
    return _default_runtime


async def close_redis_runtime() -> None:
    # Keep the singleton object stable so existing StateStore/EventBus instances
    # remain aligned during repeated lifespan cycles in tests. close() resets
    # both pools, and the same runtime can lazily reconnect if the app restarts.
    runtime = _default_runtime
    if runtime is not None:
        await runtime.close()
