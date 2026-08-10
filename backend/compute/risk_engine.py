import time
from datetime import datetime, timezone

from backend.core.schemas import PortfolioSnapshot


class RiskEngine:

    def __init__(
        self,
        max_leverage: float = 3.0,
        max_margin_pct: float = 0.6,
        max_daily_loss: float = 500.0,
        cooldown_seconds: int = 300,
    ):
        self.max_leverage = max_leverage
        self.max_margin_pct = max_margin_pct
        self.max_daily_loss = max_daily_loss
        self.cooldown_seconds = cooldown_seconds

        self.throttle_active = False
        self.throttle_reason = ""
        self.last_action_ts: float = 0.0
        self.daily_pnl: float = 0.0
        self.daily_pnl_reset_date: str = ""
        self._last_portfolio_metrics: dict = {}

    def _exposure_delta(self, positions: list[dict], proposed_action: dict) -> tuple[float, float]:
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
    def _position_mark_price(position: dict) -> float:
        return float(position.get("mark_price") or position.get("entry_price") or 0.0)

    def build_portfolio_snapshot(
        self,
        positions: list[dict],
        account_snapshot: dict | PortfolioSnapshot | None = None,
    ) -> PortfolioSnapshot:
        if isinstance(account_snapshot, PortfolioSnapshot):
            base = account_snapshot.model_dump()
        else:
            base = dict(account_snapshot or {})

        gross_exposure = 0.0
        net_exposure = 0.0
        margin_used = 0.0
        unrealized_pnl = 0.0
        asset_exposure: dict[str, float] = {}
        venue_exposure: dict[str, float] = {}
        strategy_exposure: dict[str, float] = {}

        for p in positions:
            size = float(p.get("size", 0) or 0)
            mark = self._position_mark_price(p)
            notional = abs(size * mark)
            signed_notional = size * mark
            gross_exposure += notional
            net_exposure += signed_notional
            margin_used += float(p.get("margin", 0) or 0)
            unrealized_pnl += float(p.get("unrealized_pnl", p.get("pnl", 0)) or 0)

            market = str(p.get("market", "UNKNOWN"))
            venue = str(p.get("venue", "unknown"))
            strategy = str(p.get("strategy_id", "unassigned"))
            asset_exposure[market] = asset_exposure.get(market, 0.0) + notional
            venue_exposure[venue] = venue_exposure.get(venue, 0.0) + notional
            strategy_exposure[strategy] = strategy_exposure.get(strategy, 0.0) + notional

        if "gross_exposure" in base:
            gross_exposure = float(base.get("gross_exposure") or 0.0)
        if "net_exposure" in base:
            net_exposure = float(base.get("net_exposure") or 0.0)
        if "margin_used" in base:
            margin_used = float(base.get("margin_used") or 0.0)
        if "unrealized_pnl" in base:
            unrealized_pnl = float(base.get("unrealized_pnl") or 0.0)

        cash = float(base.get("cash", 0.0) or 0.0)
        collateral = float(base.get("collateral", 0.0) or 0.0)
        realized_pnl = float(base.get("realized_pnl", 0.0) or 0.0)
        maintenance_margin = float(base.get("maintenance_margin", 0.0) or 0.0)
        open_order_exposure = float(base.get("open_order_exposure", 0.0) or 0.0)
        available_buying_power = float(base.get("available_buying_power", 0.0) or 0.0)

        equity = float(base.get("equity", 0.0) or 0.0)
        if equity <= 0:
            equity = cash + collateral + realized_pnl + unrealized_pnl
        # Legacy position-only callers previously used margin as the denominator.
        # Keep a bounded fallback rather than breaking those callers, while any
        # supplied account snapshot uses true account equity.
        if equity <= 0:
            equity = margin_used if margin_used > 0 else 1.0

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
            equity=equity,
            asset_exposure=base.get("asset_exposure") or asset_exposure,
            venue_exposure=base.get("venue_exposure") or venue_exposure,
            strategy_exposure=base.get("strategy_exposure") or strategy_exposure,
        )

    @staticmethod
    def _max_concentration(exposure: dict[str, float], denominator: float) -> float:
        if denominator <= 0 or not exposure:
            return 0.0
        return max(float(value or 0.0) for value in exposure.values()) / denominator

    def calculate_portfolio_metrics(self, snapshot: PortfolioSnapshot | dict) -> dict:
        snap = snapshot if isinstance(snapshot, PortfolioSnapshot) else PortfolioSnapshot(**snapshot)
        equity = snap.equity if snap.equity > 0 else 1.0
        gross_with_orders = snap.gross_exposure + snap.open_order_exposure
        gross_leverage = gross_with_orders / equity
        net_leverage = abs(snap.net_exposure) / equity
        margin_utilization = snap.margin_used / equity
        asset_concentration = self._max_concentration(snap.asset_exposure, gross_with_orders)
        venue_concentration = self._max_concentration(snap.venue_exposure, gross_with_orders)
        strategy_concentration = self._max_concentration(snap.strategy_exposure, gross_with_orders)
        liquidation_buffer = max(0.0, equity - snap.maintenance_margin)
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
            "gross_exposure": snap.gross_exposure,
            "net_exposure": snap.net_exposure,
            "open_order_exposure": snap.open_order_exposure,
            "available_buying_power": snap.available_buying_power,
        }

    def check_constraints(
        self,
        positions: list[dict],
        proposed_action: dict,
        execution_mode: str = "paper",
        portfolio_snapshot: dict | PortfolioSnapshot | None = None,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        reduce_quantity, increase_quantity = self._exposure_delta(positions, proposed_action)
        is_pure_reduce = reduce_quantity > 0 and increase_quantity <= 1e-12
        has_new_exposure = increase_quantity > 1e-12

        if self.throttle_active and has_new_exposure:
            reasons.append(f"Throttle active: {self.throttle_reason}")

        snapshot = self.build_portfolio_snapshot(positions, portfolio_snapshot)
        price = abs(float(proposed_action.get("price", 0) or 0))
        reduced_notional = reduce_quantity * price
        increased_notional = increase_quantity * price
        projected_gross_exposure = max(0.0, snapshot.gross_exposure - reduced_notional) + increased_notional
        projected_gross_with_orders = projected_gross_exposure + snapshot.open_order_exposure
        projected_leverage = projected_gross_with_orders / snapshot.equity if snapshot.equity > 0 else 0.0

        if has_new_exposure and projected_leverage > self.max_leverage:
            reasons.append(
                f"Leverage limit exceeded: projected {projected_leverage:.2f} > max {self.max_leverage:.2f}"
            )

        if has_new_exposure:
            requested_margin = proposed_action.get("margin")
            if requested_margin is None:
                action_margin = increased_notional / self.max_leverage if self.max_leverage > 0 else increased_notional
            else:
                full_order_size = abs(float(proposed_action.get("size", 0) or 0))
                increase_fraction = increase_quantity / full_order_size if full_order_size > 0 else 0.0
                action_margin = float(requested_margin or 0) * increase_fraction

            projected_margin_usage = (
                (snapshot.margin_used + action_margin) / snapshot.equity if snapshot.equity > 0 else 0.0
            )
            if projected_margin_usage > self.max_margin_pct:
                reasons.append(
                    f"Margin usage exceeded: projected {projected_margin_usage:.2%} > max {self.max_margin_pct:.2%}"
                )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_pnl_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = today

        if self.daily_pnl < -self.max_daily_loss and has_new_exposure:
            reasons.append(
                f"Daily loss limit breached: {self.daily_pnl:.2f} < -{self.max_daily_loss:.2f}"
            )

        if execution_mode == "live" and has_new_exposure:
            elapsed = time.time() - self.last_action_ts
            if self.last_action_ts > 0 and elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                reasons.append(f"Cooldown active: {remaining:.0f}s remaining")

        projected_snapshot = snapshot.model_copy(
            update={
                "gross_exposure": projected_gross_exposure,
                "margin_used": snapshot.margin_used + (
                    action_margin if has_new_exposure else 0.0
                ),
            }
        )
        self._last_portfolio_metrics = self.calculate_portfolio_metrics(projected_snapshot)

        allowed = len(reasons) == 0
        if allowed and not is_pure_reduce:
            self.last_action_ts = time.time()

        return allowed, reasons

    def activate_throttle(self, reason: str) -> None:
        self.throttle_active = True
        self.throttle_reason = reason

    def deactivate_throttle(self) -> None:
        self.throttle_active = False
        self.throttle_reason = ""

    def record_pnl(self, pnl: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_pnl_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = today
        self.daily_pnl += pnl

    def get_status(self) -> dict:
        return {
            "throttle_active": self.throttle_active,
            "throttle_reason": self.throttle_reason,
            "max_leverage": self.max_leverage,
            "max_margin_pct": self.max_margin_pct,
            "max_daily_loss": self.max_daily_loss,
            "cooldown_seconds": self.cooldown_seconds,
            "daily_pnl": self.daily_pnl,
            "portfolio_metrics": self._last_portfolio_metrics,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
