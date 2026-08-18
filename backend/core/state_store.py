import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.core.redis_runtime import RedisRuntime, get_redis_runtime

logger = logging.getLogger(__name__)

_THROTTLE_KEY = "risk:throttle"
_IDEMPOTENCY_PREFIX = "idem:"
_LEASE_PREFIX = "lease:"

_RELEASE_IF_OWNER_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class StateStore:

    def __init__(
        self,
        redis_url: str | None = None,
        runtime: RedisRuntime | None = None,
    ):
        if runtime is not None:
            self._runtime = runtime
        elif redis_url:
            # Explicit URLs are primarily for isolated tests/tools. Normal app
            # instances share the process-level runtime and connection pool.
            self._runtime = RedisRuntime(redis_url=redis_url)
        else:
            self._runtime = get_redis_runtime()
        self._redis_url = self._runtime.redis_url

    @property
    def runtime(self) -> RedisRuntime:
        return self._runtime

    def _key(self, key: str) -> str:
        return self._runtime.key(key)

    def get_redis(self):
        return self._runtime.get_client()

    def set_snapshot(self, key: str, data: dict[str, Any], ttl: int | None = None) -> bool:
        r = self.get_redis()
        if r is None:
            return False
        try:
            serialized = json.dumps(data, default=str)
            redis_key = self._key(key)
            if ttl:
                r.setex(redis_key, ttl, serialized)
            else:
                r.set(redis_key, serialized)
            return True
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to set snapshot for key=%s", key, exc_info=True)
            return False

    def get_snapshot(self, key: str) -> dict[str, Any] | None:
        r = self.get_redis()
        if r is None:
            return None
        try:
            raw = r.get(self._key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to get snapshot for key=%s", key, exc_info=True)
            return None

    def set_risk_throttle(self, on: bool, reason: str = "", expiry_seconds: int = 300) -> bool:
        r = self.get_redis()
        if r is None:
            return False
        try:
            data = {
                "active": on,
                "reason": reason,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            redis_key = self._key(_THROTTLE_KEY)
            if on:
                r.setex(redis_key, expiry_seconds, json.dumps(data))
            else:
                r.delete(redis_key)
            return True
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to set risk throttle", exc_info=True)
            return False

    def get_risk_throttle(self) -> dict[str, Any]:
        r = self.get_redis()
        if r is None:
            return {"active": False, "reason": "", "ts": ""}
        try:
            raw = r.get(self._key(_THROTTLE_KEY))
            if raw is None:
                return {"active": False, "reason": "", "ts": ""}
            data = json.loads(raw)
            return {
                "active": bool(data.get("active", False)),
                "reason": str(data.get("reason", "")),
                "ts": str(data.get("ts", "")),
            }
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to get risk throttle", exc_info=True)
            return {"active": False, "reason": "", "ts": ""}

    def claim_idempotency_status(
        self,
        key: str,
        *,
        ttl: int = 60,
        request_id: str | None = None,
        owner: str = "execution",
    ) -> str:
        """Return claimed, duplicate, or unavailable for one atomic claim."""
        r = self.get_redis()
        if r is None:
            return "unavailable"
        try:
            value = json.dumps(
                {
                    "request_id": request_id,
                    "state": "claimed",
                    "owner": owner,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            )
            claimed = r.set(
                self._key(f"{_IDEMPOTENCY_PREFIX}{key}"),
                value,
                ex=ttl,
                nx=True,
            )
            return "claimed" if claimed else "duplicate"
        except Exception as exc:
            self._runtime.mark_failure(exc, reset=True)
            logger.warning("Failed to claim idempotency key=%s", key, exc_info=True)
            return "unavailable"

    def claim_idempotency(
        self,
        key: str,
        *,
        ttl: int = 60,
        request_id: str | None = None,
        owner: str = "execution",
    ) -> bool:
        return self.claim_idempotency_status(
            key,
            ttl=ttl,
            request_id=request_id,
            owner=owner,
        ) == "claimed"

    def get_idempotency(self, key: str) -> dict[str, Any] | None:
        r = self.get_redis()
        if r is None:
            return None
        try:
            raw = r.get(self._key(f"{_IDEMPOTENCY_PREFIX}{key}"))
            if raw is None:
                return None
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                value = raw
            if isinstance(value, dict):
                return value
            # Backward compatibility with pre-PR #9 scalar claims such as "1".
            # Any existing legacy scalar represented a claimed key; normalize it
            # at the state-store boundary so all callers see the canonical shape.
            return {"state": "claimed", "value": value}
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to get idempotency key=%s", key, exc_info=True)
            return None

    def release_idempotency(self, key: str) -> bool:
        r = self.get_redis()
        if r is None:
            return False
        try:
            return bool(r.delete(self._key(f"{_IDEMPOTENCY_PREFIX}{key}")))
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to release idempotency key=%s", key, exc_info=True)
            return False

    def set_idempotency_key(self, key: str, ttl: int = 60) -> bool:
        # Backward-compatible boolean contract used by execution_routes: only a
        # confirmed duplicate returns False. Redis outages remain fail-open and
        # are reported through runtime health instead of becoming false 409s.
        return self.claim_idempotency_status(key, ttl=ttl) != "duplicate"

    def check_idempotency_key(self, key: str) -> bool:
        return self.get_idempotency(key) is not None

    def claim_lease(
        self,
        name: str,
        *,
        ttl: int,
        owner: str | None = None,
    ) -> str | None:
        """Claim a TTL-bound distributed lease and return its owner token.

        None means either another worker owns the lease or Redis is unavailable.
        Callers that need fail-open behavior can distinguish Redis availability
        with get_redis() before deciding whether to continue without a lease.
        """
        r = self.get_redis()
        if r is None:
            return None
        token = owner or str(uuid.uuid4())
        try:
            claimed = r.set(
                self._key(f"{_LEASE_PREFIX}{name}"),
                token,
                ex=max(1, int(ttl)),
                nx=True,
            )
            return token if claimed else None
        except Exception as exc:
            self._runtime.mark_failure(exc, reset=True)
            logger.warning("Failed to claim Redis lease=%s", name, exc_info=True)
            return None

    def release_lease(self, name: str, owner: str) -> bool:
        r = self.get_redis()
        if r is None:
            return False
        try:
            released = r.eval(
                _RELEASE_IF_OWNER_LUA,
                1,
                self._key(f"{_LEASE_PREFIX}{name}"),
                owner,
            )
            return bool(released)
        except Exception as exc:
            self._runtime.mark_failure(exc)
            logger.warning("Failed to release Redis lease=%s", name, exc_info=True)
            return False
