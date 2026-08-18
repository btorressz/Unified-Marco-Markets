import logging
from fastapi import APIRouter, Query

from backend.core.state_keys import PREDICTION_LATEST, PREDICTION_LATEST_LEGACY, prediction_symbol_key
from backend.core.state_store import StateStore
from backend.compute.macro_predictor import MacroPredictor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/predict", tags=["predict"])

_predictor = MacroPredictor()
_store = StateStore()


def _build_features(symbol: str) -> dict:
    features = {}

    idx = _store.get_snapshot("index:latest")
    if idx:
        features["tariff_momentum"] = idx.get("rate_of_change", 0.0)
        features["shock_score"] = idx.get("shock_score", 0.0)

    regime = _store.get_snapshot("regime:latest")
    if regime:
        features["funding_regime_score"] = _predictor.encode_funding_regime(regime.get("funding_regime", "neutral"))
        features["vol_regime_score"] = _predictor.encode_vol_regime(regime.get("vol_regime", "normal"))
    else:
        features["funding_regime_score"] = 0.0
        features["vol_regime_score"] = 0.3

    spreads = _store.get_snapshot("divergence:spreads")
    if spreads and isinstance(spreads, list) and len(spreads) > 0:
        features["cross_venue_spread_bps"] = spreads[0].get("spread_bps", 0)
    else:
        features["cross_venue_spread_bps"] = 0.0

    stable = _store.get_snapshot("stablecoin:health:latest") or _store.get_snapshot("stablecoin:health")
    observed_stables = []
    if isinstance(stable, dict):
        observed_stables = [
            data for data in stable.values()
            if isinstance(data, dict)
            and data.get("available") is True
            and isinstance(data.get("quality"), dict)
            and data["quality"].get("observed") is True
            and data.get("depeg_bps") is not None
        ]
    if observed_stables:
        # Preserve the existing observed-data formula; only missing-data
        # semantics change in this PR.
        depeg_sum = sum(abs(float(data.get("depeg_bps", 0.0))) for data in observed_stables)
        features["stablecoin_health_score"] = max(0.0, 1.0 - depeg_sum / 100.0)
        features["stablecoin_data_available"] = True
        features["stablecoin_observation_count"] = len(observed_stables)
    else:
        # Neutral means "no directional contribution", not "perfect peg".
        features["stablecoin_health_score"] = 0.5
        features["stablecoin_data_available"] = False
        features["stablecoin_observation_count"] = 0

    micro = _store.get_snapshot("microstructure:latest")
    if micro:
        features["orderbook_imbalance"] = micro.get("imbalance", 0.0)
    else:
        features["orderbook_imbalance"] = 0.0

    return features


def _normalize_prediction(result: dict) -> dict:
    value = result.get("prob_up_next_4h")
    if value is not None:
        result.setdefault("probability", value)
        result.setdefault("probability_up", value)
    result.setdefault("prediction_horizon", "4h")
    return result


def _save_prediction(symbol: str, result: dict) -> None:
    _store.set_snapshot(prediction_symbol_key(symbol), result, ttl=120)
    _store.set_snapshot(PREDICTION_LATEST, result, ttl=120)
    _store.set_snapshot(PREDICTION_LATEST_LEGACY, result, ttl=120)


@router.get("/latest")
def get_prediction(symbol: str = Query("SOL")):
    features = _build_features(symbol)
    result = _normalize_prediction(_predictor.predict(features))
    result["symbol"] = symbol
    _save_prediction(symbol, result)
    return result


@router.get("/explain")
def get_explanation(symbol: str = Query("SOL")):
    features = _build_features(symbol)
    result = _normalize_prediction(_predictor.predict(features))
    result["symbol"] = symbol
    result["input_features"] = features
    result["weights"] = _predictor.feature_weights
    return result
