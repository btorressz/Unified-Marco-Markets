"""Shared execution/risk policy and Redis-backed runtime-state boundary."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from backend import config
from backend.core.state_store import StateStore


@dataclass(frozen=True)
class RiskPolicy:
    max_leverage: float
    max_margin_usage: float
    max_daily_loss: float
    cooldown_seconds: int


def configured_risk_policy() -> RiskPolicy:
    return RiskPolicy(
        max_leverage=float(config.MAX_LEVERAGE),
        max_margin_usage=float(config.MAX_MARGIN_USAGE),
        max_daily_loss=float(config.MAX_DAILY_LOSS),
        cooldown_seconds=int(config.COOLDOWN_SECONDS),
    )


class RiskRuntimeState:
    """Mutable risk state shared across API/execution workers through Redis."""

    _LAST_ACTION_KEY = "risk:last_action"
    _DAILY_PNL_PREFIX = "risk:daily_pnl:"

    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    @staticmethod
    def today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _redis_key(self, key: str) -> str:
        return self.store.runtime.key(key)

    def available(self) -> bool:
        return self.store.get_redis() is not None

    def throttle(self) -> dict:
        return self.store.get_risk_throttle()

    def set_throttle(self, active: bool, reason: str = "", expiry_seconds: int = 300) -> bool:
        return self.store.set_risk_throttle(active, reason, expiry_seconds=expiry_seconds)

    def daily_pnl(self) -> float | None:
        redis = self.store.get_redis()
        if redis is None:
            return None
        try:
            raw = redis.get(self._redis_key(f"{self._DAILY_PNL_PREFIX}{self.today()}"))
            return float(raw) if raw is not None else 0.0
        except Exception:
            return None

    def record_realized_pnl(self, pnl: float, ttl_seconds: int = 172800) -> float | None:
        redis = self.store.get_redis()
        if redis is None:
            return None
        try:
            key = self._redis_key(f"{self._DAILY_PNL_PREFIX}{self.today()}")
            value = float(redis.incrbyfloat(key, float(pnl)))
            redis.expire(key, max(86400, int(ttl_seconds)))
            return value
        except Exception:
            return None

    def last_action_ts(self) -> float | None:
        snap = self.store.get_snapshot(self._LAST_ACTION_KEY)
        if not snap:
            return None
        try:
            return float(snap.get("epoch", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None

    def set_last_action_ts(self, epoch: float | None = None, cooldown_seconds: int | None = None) -> bool:
        value = float(epoch if epoch is not None else time.time())
        cooldown = int(cooldown_seconds if cooldown_seconds is not None else config.COOLDOWN_SECONDS)
        return self.store.set_snapshot(
            self._LAST_ACTION_KEY,
            {
                "epoch": value,
                "ts": datetime.fromtimestamp(value, tz=timezone.utc).isoformat(),
            },
            ttl=max(3600, cooldown * 4),
        )
