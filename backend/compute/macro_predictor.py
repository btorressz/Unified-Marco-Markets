import math
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MacroPredictor:

    def __init__(self):
        self.feature_weights = {
            "tariff_momentum": 0.25,
            "shock_score": 0.20,
            "funding_regime": 0.15,
            "vol_regime": 0.15,
            "cross_venue_spread": 0.10,
            "stablecoin_health": 0.10,
            "orderbook_imbalance": 0.05,
        }

    def sigmoid(self, x: float) -> float:
        x = max(min(x, 20.0), -20.0)
        return 1.0 / (1.0 + math.exp(-x))

    def predict(self, features: dict) -> dict:
        raw_score = 0.0
        contributions = {}

        tariff_mom = features.get("tariff_momentum", 0.0)
        s1 = -tariff_mom * 0.1
        raw_score += s1 * self.feature_weights["tariff_momentum"]
        contributions["tariff_momentum"] = round(s1 * self.feature_weights["tariff_momentum"], 4)

        shock = features.get("shock_score", 0.0)
        s2 = -shock * 0.5
        raw_score += s2 * self.feature_weights["shock_score"]
        contributions["shock_score"] = round(s2 * self.feature_weights["shock_score"], 4)

        funding = features.get("funding_regime_score", 0.0)
        s3 = funding * 2.0
        raw_score += s3 * self.feature_weights["funding_regime"]
        contributions["funding_regime"] = round(s3 * self.feature_weights["funding_regime"], 4)

        vol = features.get("vol_regime_score", 0.0)
        s4 = -abs(vol) * 0.3
        raw_score += s4 * self.feature_weights["vol_regime"]
        contributions["vol_regime"] = round(s4 * self.feature_weights["vol_regime"], 4)

        spread = features.get("cross_venue_spread_bps", 0.0)
        s5 = -abs(spread) * 0.01
        raw_score += s5 * self.feature_weights["cross_venue_spread"]
        contributions["cross_venue_spread"] = round(s5 * self.feature_weights["cross_venue_spread"], 4)

        # Missing stablecoin observations are neutral, not a perfect-peg signal.
        stable = features.get("stablecoin_health_score", 0.5)
        s6 = (stable - 0.5) * 2.0
        raw_score += s6 * self.feature_weights["stablecoin_health"]
        contributions["stablecoin_health"] = round(s6 * self.feature_weights["stablecoin_health"], 4)

        imbalance = features.get("orderbook_imbalance", 0.0)
        s7 = imbalance * 1.0
        raw_score += s7 * self.feature_weights["orderbook_imbalance"]
        contributions["orderbook_imbalance"] = round(s7 * self.feature_weights["orderbook_imbalance"], 4)

        prob_up = self.sigmoid(raw_score)
        prob_down = 1.0 - prob_up

        confidence = abs(prob_up - 0.5) * 2.0

        return {
            "prob_up_next_4h": round(prob_up, 4),
            "prob_down_next_4h": round(prob_down, 4),
            "confidence": round(confidence, 4),
            "raw_score": round(raw_score, 4),
            "feature_contributions": contributions,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def encode_funding_regime(self, regime: str) -> float:
        return {"contango": 1.0, "neutral": 0.0, "backwardation": -1.0}.get(regime, 0.0)

    def encode_vol_regime(self, regime: str) -> float:
        return {"low": 0.0, "normal": 0.3, "high": 0.7, "extreme": 1.0}.get(regime, 0.3)
