import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

VENUES = ["hyperliquid", "drift", "jupiter_spot", "stablecoins", "cash"]

CAPS = {
    "hyperliquid": 0.50,
    "drift": 0.40,
    "jupiter_spot": 0.40,
    "stablecoins": 0.80,
    "cash": 1.0,
}
FLOORS = {
    "hyperliquid": 0.0,
    "drift": 0.0,
    "jupiter_spot": 0.0,
    "stablecoins": 0.05,
    "cash": 0.0,
}

_MAX_CAPITAL_PER_VENUE = {
    "hyperliquid": 0.40,
    "drift": 0.30,
    "jupiter_spot": 0.30,
    "stablecoins": 0.70,
    "cash": 1.0,
}

_STRATEGY_CAPS = {
    "momentum": 0.25,
    "carry_arb": 0.30,
    "basis_trade": 0.25,
    "stable_rotation": 0.40,
    "defensive": 0.50,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        n = len(weights)
        return {k: 1.0 / n for k in weights}
    return {k: v / total for k, v in weights.items()}


def _apply_caps(weights: dict[str, float]) -> dict[str, float]:
    capped = {k: _clamp(weights.get(k, 0.0), FLOORS[k], CAPS[k]) for k in VENUES}
    return _normalize(capped)


def allocate(state: dict[str, Any] | None = None, *, as_of: datetime | None = None) -> dict[str, Any]:
    state = state or {}
    reasoning: list[str] = []

    predictor_conf = _clamp(float(state.get("predictor_confidence", 0.5)), 0.0, 1.0)
    predictor_prob = _clamp(float(state.get("predictor_prob", 0.5)), 0.0, 1.0)
    funding_arb = float(state.get("funding_arb_score", 0.0))
    basis_opp = float(state.get("basis_opportunity", 0.0))
    vol_regime = str(state.get("vol_regime", "normal"))
    tariff_shock = _clamp(float(state.get("tariff_shock", 0.0)), 0.0, 1.0)
    stable_health = _clamp(float(state.get("stable_health", 1.0)), 0.0, 1.0)
    exec_quality = _clamp(float(state.get("exec_quality", 0.8)), 0.0, 1.0)
    price_integrity = str(state.get("price_integrity", "ok"))
    portfolio_weights = state.get("portfolio_weights", {})

    base = {
        "hyperliquid": 0.25,
        "drift": 0.20,
        "jupiter_spot": 0.20,
        "stablecoins": 0.25,
        "cash": 0.10,
    }

    if portfolio_weights:
        hl_w = portfolio_weights.get("hl_perps", 0.25)
        dr_w = portfolio_weights.get("drift_perps", 0.20)
        jup_w = portfolio_weights.get("spot_jupiter", 0.20)
        st_w = portfolio_weights.get("stablecoins", 0.25)
        total_risky = hl_w + dr_w + jup_w + st_w
        if total_risky > 0:
            base["hyperliquid"] = hl_w / total_risky * 0.85
            base["drift"] = dr_w / total_risky * 0.85
            base["jupiter_spot"] = jup_w / total_risky * 0.85
            base["stablecoins"] = st_w / total_risky * 0.85
            base["cash"] = 0.15
        reasoning.append("seeded from portfolio optimizer weights")

    if vol_regime in ("high", "extreme"):
        shift = 0.12 if vol_regime == "extreme" else 0.08
        base["hyperliquid"] = max(base["hyperliquid"] - shift * 0.5, 0.0)
        base["drift"] = max(base["drift"] - shift * 0.3, 0.0)
        base["stablecoins"] += shift * 0.5
        base["cash"] += shift * 0.3
        reasoning.append(f"vol_regime={vol_regime}: reduced perp exposure, boosted defensive")
    elif vol_regime == "low":
        base["hyperliquid"] = min(base["hyperliquid"] + 0.05, CAPS["hyperliquid"])
        base["drift"] = min(base["drift"] + 0.03, CAPS["drift"])
        reasoning.append("vol_regime=low: allowing higher perp allocation")

    if tariff_shock > 0.6:
        shift = (tariff_shock - 0.6) * 0.3
        base["stablecoins"] = min(base["stablecoins"] + shift, CAPS["stablecoins"])
        base["cash"] = min(base["cash"] + shift * 0.5, CAPS["cash"])
        base["hyperliquid"] = max(base["hyperliquid"] - shift * 0.7, 0.0)
        base["drift"] = max(base["drift"] - shift * 0.5, 0.0)
        reasoning.append(f"tariff_shock={tariff_shock:.2f}: defensive rotation activated")

    if stable_health < 0.7:
        penalty = (0.7 - stable_health) * 0.20
        base["stablecoins"] = max(base["stablecoins"] - penalty, FLOORS["stablecoins"])
        base["cash"] += penalty
        reasoning.append(f"stable_health={stable_health:.2f}: reduced stablecoin, shifted to cash")

    if funding_arb > 0.5:
        boost = funding_arb * 0.08
        base["drift"] = min(base["drift"] + boost * 0.5, CAPS["drift"])
        base["hyperliquid"] = min(base["hyperliquid"] + boost * 0.5, CAPS["hyperliquid"])
        reasoning.append(f"funding_arb={funding_arb:.2f}: boosted perp venues for arb capture")

    if basis_opp > 0.5:
        base["jupiter_spot"] = min(base["jupiter_spot"] + 0.05, CAPS["jupiter_spot"])
        reasoning.append(f"basis_opp={basis_opp:.2f}: boosted spot for basis trade")

    if exec_quality < 0.5:
        shift = (0.5 - exec_quality) * 0.15
        base["jupiter_spot"] = max(base["jupiter_spot"] - shift, 0.0)
        base["cash"] += shift
        reasoning.append(f"exec_quality={exec_quality:.2f}: reduced spot due to poor execution conditions")

    if price_integrity == "warning":
        base["hyperliquid"] = max(base["hyperliquid"] * 0.85, 0.0)
        base["drift"] = max(base["drift"] * 0.85, 0.0)
        reasoning.append("price_integrity=warning: 15% reduction in perp venues")

    weights = _apply_caps(base)

    confidence = _estimate_confidence(predictor_conf, price_integrity, vol_regime, exec_quality)

    max_capital = {v: _MAX_CAPITAL_PER_VENUE[v] for v in VENUES}
    strategy_caps = dict(_STRATEGY_CAPS)

    risk_adj_returns = {
        "hyperliquid": _clamp(weights["hyperliquid"] * (1.0 + funding_arb * 0.5) * exec_quality, 0.0, 0.5),
        "drift": _clamp(weights["drift"] * (1.0 + funding_arb * 0.4) * exec_quality, 0.0, 0.4),
        "jupiter_spot": _clamp(weights["jupiter_spot"] * (1.0 + basis_opp * 0.3) * exec_quality, 0.0, 0.4),
        "stablecoins": _clamp(weights["stablecoins"] * stable_health * 0.06, 0.0, 0.1),
        "cash": 0.04,
    }

    reasoning.append("proposal only — no auto-trade")

    return {
        "weights": {v: round(weights[v], 6) for v in VENUES},
        "max_capital_per_venue": max_capital,
        "max_capital_per_strategy": strategy_caps,
        "risk_adjusted_expected_returns": {v: round(risk_adj_returns[v], 6) for v in VENUES},
        "confidence": round(confidence, 3),
        "reasoning": reasoning,
        "inputs": {
            "predictor_confidence": predictor_conf,
            "predictor_prob": predictor_prob,
            "funding_arb_score": funding_arb,
            "basis_opportunity": basis_opp,
            "vol_regime": vol_regime,
            "tariff_shock": tariff_shock,
            "stable_health": stable_health,
            "exec_quality": exec_quality,
            "price_integrity": price_integrity,
        },
        "ts": (as_of or datetime.now(timezone.utc)).isoformat(),
    }


def _estimate_confidence(
    predictor_conf: float,
    price_integrity: str,
    vol_regime: str,
    exec_quality: float,
) -> float:
    score = predictor_conf * 0.4
    integrity_score = {"ok": 0.3, "warning": 0.15, "error": 0.0}.get(price_integrity, 0.1)
    score += integrity_score
    vol_score = {"low": 0.2, "normal": 0.2, "high": 0.1, "extreme": 0.05}.get(vol_regime, 0.15)
    score += vol_score
    score += exec_quality * 0.10
    return _clamp(score, 0.1, 0.95)


def execution_preview(order: dict[str, Any], allocation: dict[str, Any] | None = None, portfolio: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate allocation weights into proposal-only pre-trade sizing constraints."""
    allocation = allocation or allocate({})
    portfolio = portfolio or {}
    venue = str(order.get("venue", "hyperliquid")).lower()
    market = str(order.get("market", "SOL-USD")).upper()
    size = max(0.0, float(order.get("size") or 0.0))
    price = max(0.0, float(order.get("price") or 0.0))
    notional = size * price if price > 0 else size
    equity = max(1.0, float(portfolio.get("portfolio_value", order.get("portfolio_value", 100000.0)) or 100000.0))
    cash = max(0.0, float(portfolio.get("available_cash", order.get("available_cash", equity * allocation.get("weights", {}).get("cash", 0.10))) or 0.0))
    current_exposure = float(portfolio.get("current_exposure", order.get("current_exposure", 0.0)) or 0.0)
    venue_exposure = float((portfolio.get("venue_exposure", {}) or {}).get(venue, order.get("venue_exposure", 0.0)) or 0.0)
    asset_exposure = float((portfolio.get("asset_exposure", {}) or {}).get(market, order.get("asset_exposure", 0.0)) or 0.0)
    target_weight = float((allocation.get("weights", {}) or {}).get(venue, 0.0))
    venue_cap = float((allocation.get("max_capital_per_venue", {}) or {}).get(venue, _MAX_CAPITAL_PER_VENUE.get(venue, 0.25)))
    asset_cap = float(order.get("asset_cap", 0.20))
    portfolio_risk_cap = float(order.get("portfolio_risk_cap", 0.85))
    warnings: list[str] = []
    candidates = {
        "target_allocation_room": max(0.0, target_weight * equity - venue_exposure),
        "venue_cap_room": max(0.0, venue_cap * equity - venue_exposure),
        "asset_cap_room": max(0.0, asset_cap * equity - asset_exposure),
        "portfolio_risk_room": max(0.0, portfolio_risk_cap * equity - current_exposure),
        "available_cash": cash,
    }
    allowed_notional = min(candidates.values()) if candidates else 0.0
    allowed_size = allowed_notional / price if price > 0 else allowed_notional
    suggested_size = min(size, allowed_size)
    blocked_reason = None
    if size <= 0:
        blocked_reason = "size must be positive"
    elif suggested_size <= 0:
        blocked_reason = "no allocation room available"
    elif suggested_size < size:
        warnings.append("Proposed size exceeds one or more allocation/risk caps; use suggested_size")
    if allocation.get("confidence", 1.0) < 0.35:
        warnings.append("Allocator confidence is low; preview is degraded")
    return {
        "preview": True,
        "paper_mode_only": True,
        "auto_trade": False,
        "venue": venue,
        "market": market,
        "target_allocation": round(target_weight, 6),
        "current_allocation": round(venue_exposure / equity, 6),
        "proposed_notional": round(notional, 4),
        "proposed_order_impact": round(notional / equity, 6),
        "allowed_size": round(max(0.0, allowed_size), 8),
        "suggested_size": round(max(0.0, suggested_size), 8),
        "blocked_reason": blocked_reason,
        "warnings": warnings,
        "constraints": {k: round(v, 4) for k, v in candidates.items()},
        "reasoning": ["checked target allocation, venue cap, asset cap, portfolio risk cap, available cash, and current exposure", "proposal-only preview; no order routed"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
