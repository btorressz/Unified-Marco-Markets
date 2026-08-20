import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.core.schemas import RuleActionResponse
from backend.compute.rules_engine import RulesEngine
from backend.compute.adaptive_weights import compute_weights
from backend.core.state_store import StateStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules", tags=["rules"])

_rules_engine = RulesEngine()
_state_store = StateStore()


@router.get("/evaluate", response_model=list[RuleActionResponse])
def evaluate_rules():
    try:
        snapshot = _state_store.get_snapshot("desk:context") or {}
        context = {
            "tariff_rate_of_change": snapshot.get("tariff_rate_of_change", 0.0),
            "vol_regime": snapshot.get("vol_regime", "normal"),
            "shock_score": snapshot.get("shock_score", 0.0),
            "divergence_alert_active": snapshot.get("divergence_alert_active", False),
            "funding_regime_flipped": snapshot.get("funding_regime_flipped", False),
            "carry_score": snapshot.get("carry_score", 0.0),
            "venue": snapshot.get("venue", "paper"),
            "market": snapshot.get("market", "SOL-PERP"),
            "suggested_size": snapshot.get("suggested_size", 0.0),
        }
        actions = _rules_engine.evaluate(context)
        results = []
        for a in actions:
            results.append(RuleActionResponse(
                rule_name=a["rule_name"],
                rule_id=a.get("rule_id"), rule_version=a.get("rule_version"),
                evaluation_type=a.get("evaluation_type"), expected_direction=a.get("expected_direction"),
                action_type=a["action_type"],
                venue=a.get("venue", ""),
                market=a.get("market", ""),
                side=a.get("side", ""),
                size=a.get("size", 0.0),
                reason=a.get("reason", ""),
                approved=False,
                ts=datetime.now(timezone.utc),
            ))
        return results
    except Exception as exc:
        logger.error("Error evaluating rules: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to evaluate rules")


@router.get("/status")
def get_status():
    try:
        rules_info = []
        for rule in _rules_engine.rules:
            rules_info.append({key: value for key, value in rule.items() if key != "condition"})
        return {
            "rules": rules_info,
            "rule_count": len(rules_info),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Error fetching rules status: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch rules status")


@router.get("/adaptive-weights")
def get_adaptive_weights():
    try:
        idx = _state_store.get_snapshot("index:latest") or {}
        regime = _state_store.get_snapshot("regime:latest") or {}
        from backend.core.state_keys import funding_snapshot_key
        funding = _state_store.get_snapshot(funding_snapshot_key("hyperliquid", "SOL-PERP")) or {}

        shock_score = idx.get("shock_score", 0)
        tariff_index = idx.get("tariff_index", 0)
        vol_regime = regime.get("vol_regime", "normal")
        funding_skew = funding.get("normalized_funding_rate") if funding.get("contract_version") == 1 else None

        result = compute_weights(shock_score, funding_skew or 0, vol_regime, tariff_index)
        result["funding_available"] = funding_skew is not None
        return result
    except Exception as exc:
        logger.error("Error computing adaptive weights: %s", exc, exc_info=True)
        return {
            "weights": {"macro": 0.25, "carry": 0.25, "microstructure": 0.25, "momentum": 0.25},
            "adaptive_enabled": False,
            "adjustments": [],
            "ts": datetime.now(timezone.utc).isoformat(),
        }
