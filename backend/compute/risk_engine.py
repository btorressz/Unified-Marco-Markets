import math
import time
from datetime import datetime, timezone

from backend.core.schemas import PortfolioSnapshot
from backend.core.risk_policy import RiskRuntimeState, configured_risk_policy


class RiskEngine:

    def __init__(
        self,
        max_leverage: float | None = None,
        max_margin_pct: float | None = None,
        max_daily_loss: float | None = None,
        cooldown_seconds: int | None = None,
        runtime_state: RiskRuntimeState | None = None,
    ):
        policy = configured_risk_policy()
        self.max_leverage = float(policy.max_leverage if max_leverage is None else max_leverage)
        self.max_margin_pct = float(policy.max_margin_usage if max_margin_pct is None else max_margin_pct)
        self.max_daily_loss = float(policy.max_daily_loss if max_daily_loss is None else max_daily_loss)
        self.cooldown_seconds = int(policy.cooldown_seconds if cooldown_seconds is None else cooldown_seconds)

        self.runtime_state = runtime_state or RiskRuntimeState()
        self.throttle_active = False
        self.throttle_reason = ""
        self.last_action_ts: float = 0.0
        self.daily_pnl: float = 0.0
        self.daily_pnl_reset_date: str = ""
        self.last_metrics: dict = {}

    def _sync_shared_state(self) -> None:
        if not self.runtime_state.available():
            return
        throttle = self.runtime_state.throttle()
        self.throttle_active = bool(throttle.get("active", False))
        self.throttle_reason = str(throttle.get("reason", ""))
        shared_pnl = self.runtime_state.daily_pnl()
        if shared_pnl is not None:
            self.daily_pnl = float(shared_pnl)
            self.daily_pnl_reset_date = self.runtime_state.today()
        shared_last_action = self.runtime_state.last_action_ts()
        if shared_last_action is not None:
            self.last_action_ts = float(shared_last_action)

    def _exposure_delta(self, positions: list[dict], proposed_action: dict) -> tuple[float, float]:
        """Return (reduce_quantity, increase_quantity) for the proposed order."""
        side = str(proposed_action.get("side", "")).lower()
        market = str(proposed_action.get("market", ""))
        venue = str(proposed_action.get("venue", ""))
        order_size = abs(float(proposed_action.get("size", 0) or 0))
        key = f"{venue}:{market}"

        opposite_position_qty = 0.0
        for p in positions:
            p_key = f"{p.get('venue', '')}:{p.get('market', '')}"
            if p_key != key:
                continue
            p_size = float(p.get("size", 0) or 0)
            if (p_size > 0 and side == "sell") or (p_size < 0 and side == "buy"):
                opposite_position_qty += abs(p_size)

        reduce_quantity = min(order_size, opposite_position_qty)
        increase_quantity = max(order_size - reduce_quantity, 0.0)
        return reduce_quantity, increase_quantity

    def _is_reducing(self, positions: list[dict], proposed_action: dict) -> bool:
        reduce_quantity, increase_quantity = self._exposure_delta(positions, proposed_action)
        return reduce_quantity > 0 and increase_quantity <= 1e-12

    @staticmethod
    def _position_price(position: dict) -> float:
        return abs(float(
            position.get("mark_price")
            or position.get("price")
            or position.get("entry_price")
            or 0.0
        ))

    def build_portfolio_snapshot(
        self,
        positions: list[dict],
        account: dict | PortfolioSnapshot | None = None,
        open_orders: list[dict] | None = None,
    ) -> PortfolioSnapshot:
        if isinstance(account, PortfolioSnapshot):
            base = account.model_dump()
        else:
            base = dict(account or {})

        gross_exposure = 0.0
        net_exposure = 0.0
        margin_used = 0.0
        unrealized_pnl = float(base.get("unrealized_pnl", 0.0) or 0.0)
        asset_exposure: dict[str, float] = {}
        venue_exposure: dict[str, float] = {}
        strategy_exposure: dict[str, float] = {}

        if "unrealized_pnl" not in base:
            unrealized_pnl = 0.0

        for position in positions:
            size = float(position.get("size", 0.0) or 0.0)
            price = self._position_price(position)
            notional = abs(size * price)
            signed_notional = size * price
            market = str(position.get("market", "UNKNOWN"))
            venue = str(position.get("venue", "unknown"))
            strategy = str(position.get("strategy_id") or "unassigned")

            gross_exposure += notional
            net_exposure += signed_notional
            margin_used += float(position.get("margin", 0.0) or 0.0)
            asset_exposure[market] = asset_exposure.get(market, 0.0) + notional
            venue_exposure[venue] = venue_exposure.get(venue, 0.0) + notional
            strategy_exposure[strategy] = strategy_exposure.get(strategy, 0.0) + notional

            if "unrealized_pnl" not in base:
                unrealized_pnl += float(
                    position.get("unrealized_pnl", position.get("pnl", 0.0)) or 0.0
                )

        open_order_exposure = float(base.get("open_order_exposure", 0.0) or 0.0)
        if open_orders:
            open_order_exposure = sum(
                abs(
                    float(order.get("size", 0.0) or 0.0)
                    * float(order.get("price", 0.0) or 0.0)
                )
                for order in open_orders
            )

        if "gross_exposure" in base:
            gross_exposure = float(base.get("gross_exposure") or 0.0)
        if "net_exposure" in base:
            net_exposure = float(base.get("net_exposure") or 0.0)
        if "margin_used" in base:
            margin_used = float(base.get("margin_used") or 0.0)

        cash = float(base.get("cash", 0.0) or 0.0)
        collateral = float(base.get("collateral", 0.0) or 0.0)
        realized_pnl = float(base.get("realized_pnl", 0.0) or 0.0)

        if cash == 0.0 and collateral == 0.0:
            collateral = max(margin_used, 1.0)

        equity = cash + collateral + realized_pnl + unrealized_pnl
        available_buying_power = float(
            base.get(
                "available_buying_power",
                max(equity * self.max_leverage - gross_exposure - open_order_exposure, 0.0),
            )
            or 0.0
        )
        maintenance_margin = float(base.get("maintenance_margin", margin_used * 0.5) or 0.0)

        return PortfolioSnapshot(
            cash=cash,
            collateral=collateral,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            margin_used=margin_used,
            maintenance_margin=maintenance_margin,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            open_order_exposure=open_order_exposure,
            available_buying_power=available_buying_power,
            asset_exposure=dict(base.get("asset_exposure") or asset_exposure),
            venue_exposure=dict(base.get("venue_exposure") or venue_exposure),
            strategy_exposure=dict(base.get("strategy_exposure") or strategy_exposure),
        )

    def calculate_metrics(self, snapshot: PortfolioSnapshot) -> dict:
        equity = snapshot.equity
        gross_with_orders = snapshot.gross_exposure + snapshot.open_order_exposure

        gross_leverage = gross_with_orders / equity if equity > 0 else float("inf")
        net_leverage = abs(snapshot.net_exposure) / equity if equity > 0 else float("inf")
        margin_utilization = snapshot.margin_used / equity if equity > 0 else float("inf")

        asset_concentration = (
            max(snapshot.asset_exposure.values()) / snapshot.gross_exposure
            if snapshot.gross_exposure > 0 and snapshot.asset_exposure
            else 0.0
        )
        venue_concentration = (
            max(snapshot.venue_exposure.values()) / snapshot.gross_exposure
            if snapshot.gross_exposure > 0 and snapshot.venue_exposure
            else 0.0
        )
        strategy_concentration = (
            max(snapshot.strategy_exposure.values()) / snapshot.gross_exposure
            if snapshot.gross_exposure > 0 and snapshot.strategy_exposure
            else 0.0
        )
        liquidation_buffer = max(equity - snapshot.maintenance_margin, 0.0)
        liquidation_buffer_pct = liquidation_buffer / equity if equity > 0 else 0.0

        return {
            "equity": equity,
            "gross_leverage": gross_leverage,
            "net_leverage": net_leverage,
            "margin_utilization": margin_utilization,
            "asset_concentration": asset_concentration,
            "venue_concentration": venue_concentration,
            "strategy_concentration": strategy_concentration,
            "liquidation_buffer": liquidation_buffer,
            "liquidation_buffer_pct": liquidation_buffer_pct,
            "available_buying_power": snapshot.available_buying_power,
            "gross_exposure": snapshot.gross_exposure,
            "net_exposure": snapshot.net_exposure,
            "open_order_exposure": snapshot.open_order_exposure,
        }

    def _finite_action_reasons(self, proposed_action: dict) -> list[str]:
        reasons: list[str] = []
        for field in ("size", "price", "margin", "slippage_bps"):
            value = proposed_action.get(field)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                reasons.append(f"invalid_{field}: must be numeric")
                continue
            if not math.isfinite(numeric):
                reasons.append(f"invalid_{field}: must be finite")
        return reasons

    def check_constraints(
        self,
        positions: list[dict],
        proposed_action: dict,
        execution_mode: str = "paper",
        portfolio_snapshot: dict | PortfolioSnapshot | None = None,
        as_of: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        self._sync_shared_state()
        reasons = self._finite_action_reasons(proposed_action)
        if reasons:
            self.last_metrics = {}
            return False, reasons

        reduce_quantity, increase_quantity = self._exposure_delta(positions, proposed_action)
        is_pure_reduce = reduce_quantity > 0 and increase_quantity <= 1e-12
        has_new_exposure = increase_quantity > 1e-12

        if self.throttle_active and has_new_exposure:
            reasons.append(f"Throttle active: {self.throttle_reason}")

        snapshot = self.build_portfolio_snapshot(positions, account=portfolio_snapshot)
        equity = snapshot.equity
        price = abs(float(proposed_action.get("price", 0) or 0))
        reduced_notional = reduce_quantity * price
        increased_notional = increase_quantity * price
        projected_gross = (
            max(0.0, snapshot.gross_exposure - reduced_notional)
            + increased_notional
            + snapshot.open_order_exposure
        )
        projected_leverage = projected_gross / equity if equity > 0 else float("inf")

        if has_new_exposure and projected_leverage > self.max_leverage:
            reasons.append(
                f"Leverage limit exceeded: projected {projected_leverage:.2f} > max {self.max_leverage:.2f}"
            )

        projected_margin_usage = 0.0
        if has_new_exposure:
            requested_margin = proposed_action.get("margin")
            if requested_margin is None:
                action_margin = increased_notional / self.max_leverage if self.max_leverage > 0 else increased_notional
            else:
                full_order_size = abs(float(proposed_action.get("size", 0) or 0))
                increase_fraction = increase_quantity / full_order_size if full_order_size > 0 else 0.0
                action_margin = float(requested_margin or 0) * increase_fraction

            released_margin = reduced_notional / self.max_leverage if self.max_leverage > 0 else 0.0
            projected_margin = max(0.0, snapshot.margin_used - released_margin) + action_margin
            projected_margin_usage = projected_margin / equity if equity > 0 else float("inf")
            if projected_margin_usage > self.max_margin_pct:
                reasons.append(
                    f"Margin usage exceeded: projected {projected_margin_usage:.2%} > max {self.max_margin_pct:.2%}"
                )

        clock = as_of or datetime.now(timezone.utc)
        today = clock.strftime("%Y-%m-%d")
        if self.daily_pnl_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = today

        if self.daily_pnl < -self.max_daily_loss and has_new_exposure:
            reasons.append(
                f"Daily loss limit breached: {self.daily_pnl:.2f} < -{self.max_daily_loss:.2f}"
            )

        if execution_mode == "live" and has_new_exposure:
            elapsed = clock.timestamp() - self.last_action_ts
            if self.last_action_ts > 0 and elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                reasons.append(f"Cooldown active: {remaining:.0f}s remaining")

        self.last_metrics = self.calculate_metrics(snapshot) | {
            "projected_gross_leverage": projected_leverage,
            "projected_margin_utilization": projected_margin_usage,
        }

        allowed = len(reasons) == 0
        if allowed and not is_pure_reduce:
            self.last_action_ts = clock.timestamp()
            if self.runtime_state.available():
                self.runtime_state.set_last_action_ts(self.last_action_ts, self.cooldown_seconds)

        return allowed, reasons

    def activate_throttle(self, reason: str) -> None:
        self.throttle_active = True
        self.throttle_reason = reason
        if self.runtime_state.available():
            self.runtime_state.set_throttle(True, reason, expiry_seconds=max(300, self.cooldown_seconds))

    def deactivate_throttle(self) -> None:
        self.throttle_active = False
        self.throttle_reason = ""
        if self.runtime_state.available():
            self.runtime_state.set_throttle(False)

    def record_pnl(self, pnl: float) -> None:
        value = float(pnl)
        if not math.isfinite(value):
            raise ValueError("PnL must be finite")
        if self.runtime_state.available():
            shared = self.runtime_state.record_realized_pnl(value)
            if shared is not None:
                self.daily_pnl = shared
                self.daily_pnl_reset_date = self.runtime_state.today()
                return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_pnl_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = today
        self.daily_pnl += value

    def get_status(self) -> dict:
        self._sync_shared_state()
        return {
            "throttle_active": self.throttle_active,
            "throttle_reason": self.throttle_reason,
            "max_leverage": self.max_leverage,
            "max_margin_pct": self.max_margin_pct,
            "max_daily_loss": self.max_daily_loss,
            "cooldown_seconds": self.cooldown_seconds,
            "daily_pnl": self.daily_pnl,
            "runtime_state": "shared" if self.runtime_state.available() else "process_fallback",
            "portfolio_metrics": self.last_metrics,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
