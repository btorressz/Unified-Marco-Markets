"""Pure spot/perpetual basis calculation; perpetual basis has no maturity."""
from datetime import datetime, timezone

MAX_LEG_AGE_SECONDS = 180
MAX_TIMESTAMP_SKEW_SECONDS = 120
MAX_FUTURE_SKEW_SECONDS = 30


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def compute_basis_observation(*, symbol, venue, market, spot_source, spot_price,
                              spot_ts, perp_price, perp_ts, now=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    if spot_price is None or spot_price <= 0: reasons.append("missing_or_invalid_spot")
    if perp_price is None or perp_price <= 0: reasons.append("missing_or_invalid_perp")
    spot_dt, perp_dt = _dt(spot_ts), _dt(perp_ts)
    if not spot_dt or not perp_dt: reasons.append("invalid_timestamp")
    base = {"contract_version": 1, "symbol": symbol, "venue": venue, "market": market,
            "spot_source": spot_source, "spot_price": spot_price, "perp_price": perp_price,
            "spot_ts": spot_dt, "perp_ts": perp_dt, "annualized_basis_bps": None,
            "annualization_defined": False, "net_carry": None, "research_only": True,
            "execution_eligible": False, "retrieved_at": now, "lineage": {}, "metadata": {}}
    if reasons:
        return {**base, "available": False, "reasons": reasons, "basis_bps": None,
                "aligned": False, "fresh": False, "timestamp_skew_seconds": None}
    skew = abs((spot_dt-perp_dt).total_seconds())
    spot_age, perp_age = (now-spot_dt).total_seconds(), (now-perp_dt).total_seconds()
    aligned = skew <= MAX_TIMESTAMP_SKEW_SECONDS
    fresh = (max(spot_age, perp_age) <= MAX_LEG_AGE_SECONDS and
             min(spot_age, perp_age) >= -MAX_FUTURE_SKEW_SECONDS)
    if not aligned: reasons.append("timestamp_skew_exceeded")
    if min(spot_age, perp_age) < -MAX_FUTURE_SKEW_SECONDS: reasons.append("future_leg")
    elif not fresh: reasons.append("stale_leg")
    basis = ((perp_price-spot_price)/spot_price)*10_000 if not reasons else None
    return {**base, "available": not reasons, "reasons": reasons, "basis_bps": basis,
            "timestamp_skew_seconds": skew, "spot_age_seconds": spot_age,
            "perp_age_seconds": perp_age, "max_leg_age_seconds": max(spot_age,perp_age),
            "aligned": aligned, "fresh": fresh, "observed_at": max(spot_dt,perp_dt)}


def compute_basis(hl_perp_price, drift_perp_price, spot_price, **kwargs):
    """Legacy shape without inventing timestamps or annualization."""
    if not spot_price or spot_price <= 0:
        return {"available": False, "hl_spot_basis_bps": None, "drift_spot_basis_bps": None,
                "annualized_basis_bps": None, "annualization_defined": False, "net_carry": None,
                "error": "invalid_spot_price"}
    return {"available": True, "hl_spot_basis_bps": round((hl_perp_price-spot_price)/spot_price*10000,2),
            "drift_spot_basis_bps": round((drift_perp_price-spot_price)/spot_price*10000,2) if drift_perp_price > 0 else None,
            "annualized_basis_bps": None, "annualization_defined": False, "net_carry": None}


def assess_feasibility(spread_bps, liquidity_depth=1.0, integrity_status="ok"):
    score = 100 - (40 if abs(spread_bps)>100 else 20 if abs(spread_bps)>50 else 10 if abs(spread_bps)>20 else 0)
    if liquidity_depth < .3: score -= 30
    elif liquidity_depth < .6: score -= 15
    elif liquidity_depth < .8: score -= 5
    if integrity_status.lower() != "ok": score -= 25
    return max(0,min(100,score))
