import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class StableYieldCalculator:

    def compute_annualized_carry(
        self,
        funding_rate: float,
        interval_seconds: int,
    ) -> float:
        from backend.core.derivatives_observations import annualize_rate
        return annualize_rate(funding_rate, interval_seconds)

    def compute_net_carry(
        self,
        funding_rate: float,
        spread_bps: float = 0.0,
        fee_bps: float = 1.0,
        interval_seconds: int | None = None,
    ) -> dict:
        if interval_seconds is None:
            return {"available": False, "reason": "interval_seconds_required"}
        gross = self.compute_annualized_carry(funding_rate, interval_seconds)
        slippage_cost = spread_bps / 10000.0 * 2.0
        fee_cost = fee_bps / 10000.0 * 2.0
        entry_exit_cost_annual = (slippage_cost + fee_cost) * 12.0
        net = gross - entry_exit_cost_annual

        risk_factor = max(0.3, 1.0 - abs(gross) * 0.5)
        risk_adjusted = net * risk_factor

        return {
            "gross_carry_annual": round(gross, 6),
            "net_carry_annual": round(net, 6),
            "risk_adjusted_carry": round(risk_adjusted, 6),
            "entry_exit_cost_annual": round(entry_exit_cost_annual, 6),
            "risk_factor": round(risk_factor, 4),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def compute_carry_scores(self, funding_rates: dict[str, dict], spreads: dict[str, float] | None = None) -> dict:
        spreads = spreads or {}
        results = {}
        for venue, observation in funding_rates.items():
            spread = spreads.get(venue, 5.0)
            results[venue] = self.compute_net_carry(observation["rate"], spread_bps=spread, interval_seconds=observation.get("interval_seconds"))
        return results

    def detect_carry_regime_flip(self, current_carry: float, previous_carry: float) -> bool:
        return (current_carry > 0 and previous_carry <= 0) or (current_carry <= 0 and previous_carry > 0)
