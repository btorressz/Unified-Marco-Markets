"""Shared execution/risk policy and runtime-state boundary.

This module keeps the existing RiskEngine formulas intact while ensuring API and
execution callers use the same configured limits and Redis-backed mutable risk
state. Redis outages fall back to the engine's existing process-local state;
live fail-closed behavior is enforced separately at the execution API boundary.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from backend import config
from backend.compute.risk_engine import RiskEngine
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
    """Redis-backed mutable state shared by risk API and execution workers."""

    _LAST_ACTION_KEY = "risk:last_action"
    _DAILY_PNL_PREFIX = "risk:daily_pnl:"

    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _redis_key(self, key: str) -> str:
        return self.store.runtime.key(key)

    def throttle(self) -> dict:
        return self.store.get_risk_throttle()

    def set_throttle(self, active: bool, reason: str = "", expiry_seconds: int = 300) -> bool:
        return self.store.set_risk_throttle(active, reason, expiry_seconds=expiry_seconds)

    def daily_pnl(self) -> float | None:
        redis = self.store.get_redis()
        if redis is None:
            return None
        try:
            raw = redis.get(self._redis_key(f"{self._DAILY_PNL_PREFIX}{self._today()}"))
            return float(raw) if raw is not None else 0.0
        except Exception:
            return None

    def record_realized_pnl(self, pnl: float, ttl_seconds: int = 172800) -> float | None:
        redis = self.store.get_redis()
        if redis is None:
            return None
        try:
            key = self._redis_key(f"{self._DAILY_PNL_PREFIX}{self._today()}")
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

    def set_last_action_ts(self, epoch: float | None = None) -> bool:
        value = float(epoch if epoch is not None else time.time())
        return self.store.set_snapshot(
            self._LAST_ACTION_KEY,
            {
                "epoch": value,
                "ts": datetime.fromtimestamp(value, tz=timezone.utc).isoformat(),
            },
            ttl=max(3600, int(config.COOLDOWN_SECONDS) * 4),
        )


class SharedRiskEngine(RiskEngine):
    """Configured RiskEngine with shared mutable runtime state."""

    def __init__(self, policy: RiskPolicy | None = None, state: RiskRuntimeState | None = None):
        policy = policy or configured_risk_policy()
        super().__init__(
            max_leverage=policy.max_leverage,
            max_margin_pct=policy.max_margin_usage,
            max_daily_loss=policy.max_daily_loss,
            cooldown_seconds=policy.cooldown_seconds,
        )
        self.policy = policy
        self.runtime_state = state or RiskRuntimeState()

    def _sync_from_shared(self) -> None:
        throttle = self.runtime_state.throttle()
        self.throttle_active = bool(throttle.get("active", False))
        self.throttle_reason = str(throttle.get("reason", ""))

        shared_pnl = self.runtime_state.daily_pnl()
        if shared_pnl is not None:
            self.daily_pnl = float(shared_pnl)
            self.daily_pnl_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        shared_last_action = self.runtime_state.last_action_ts()
        if shared_last_action is not None:
            self.last_action_ts = float(shared_last_action)

    def check_constraints(self, *args, **kwargs):
        self._sync_from_shared()
        before = self.last_action_ts
        allowed, reasons = super().check_constraints(*args, **kwargs)
        if allowed and self.last_action_ts > before:
            self.runtime_state.set_last_action_ts(self.last_action_ts)
        return allowed, reasons

    def activate_throttle(self, reason: str) -> None:
        super().activate_throttle(reason)
        self.runtime_state.set_throttle(True, reason, expiry_seconds=max(300, self.cooldown_seconds))

    def deactivate_throttle(self) -> None:
        super().deactivate_throttle()
        self.runtime_state.set_throttle(False)

    def record_pnl(self, pnl: float) -> None:
        shared = self.runtime_state.record_realized_pnl(float(pnl))
        if shared is None:
            super().record_pnl(float(pnl))
        else:
            self.daily_pnl = shared
            self.daily_pnl_reset_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_status(self) -> dict:
        self._sync_from_shared()
        status = super().get_status()
        status["policy_source"] = "configured_shared"
        status["runtime_state"] = "shared" if self.runtime_state.store.get_redis() is not None else "process_fallback"
        return status


def configured_risk_engine(store: StateStore | None = None) -> SharedRiskEngine:
    state = RiskRuntimeState(store=store)
    return SharedRiskEngine(policy=configured_risk_policy(), state=state)
