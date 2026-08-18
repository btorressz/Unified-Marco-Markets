from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compute.geopolitical_evidence import expected_impact_evidence

ASSET_MAP = {
    "SPY": ("equity", "Broad Market"), "QQQ": ("equity", "Technology"), "IWM": ("equity", "Small Caps"),
    "SMH": ("etf", "Semiconductors"), "SOXX": ("etf", "Semiconductors"), "XLE": ("etf", "Energy"), "XLI": ("etf", "Industrials"), "XRT": ("etf", "Retail"), "ITA": ("etf", "Defense"), "GLD": ("etf", "Gold"), "SLV": ("etf", "Silver"), "USO": ("etf", "Oil"),
    "AAPL": ("stock", "Technology"), "NVDA": ("stock", "Semiconductors"), "AMD": ("stock", "Semiconductors"), "TSLA": ("stock", "Autos"), "NKE": ("stock", "Retail/Apparel"), "WMT": ("stock", "Retail"), "CAT": ("stock", "Machinery"), "DE": ("stock", "Machinery"), "BA": ("stock", "Aerospace"), "XOM": ("stock", "Energy"), "CVX": ("stock", "Energy"),
    "BTC": ("crypto", "Crypto"), "ETH": ("crypto", "Crypto"), "SOL": ("crypto", "Crypto"), "USDC": ("stablecoin", "Stablecoin"), "USDT": ("stablecoin", "Stablecoin"), "DAI": ("stablecoin", "Stablecoin"),
}
DEFENSIVE = {"GLD", "SLV", "ITA", "XLE", "XOM", "CVX", "USO"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_market_impact(index: dict[str, Any] | None = None, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    idx = index or {}
    score = float(idx.get("overall_score", 45.0) or 45.0)
    event_ids = [e.get("event_id") for e in (events or [])[:5]]
    evidence = expected_impact_evidence(related_events=events)
    rows = []
    for asset, (asset_class, sector) in ASSET_MAP.items():
        defensive = asset in DEFENSIVE
        stable = asset_class == "stablecoin"
        impact = min(100.0, score * (0.45 if stable else 0.75 if defensive else 1.0))
        if stable:
            direction = "mixed" if score >= 60 else "neutral"
        elif defensive:
            direction = "bullish" if score >= 45 else "neutral"
        else:
            direction = "bearish" if score >= 45 else "neutral"
        rows.append({
            "asset": asset, "asset_class": asset_class, "sector": sector,
            "impact_score": round(impact, 2), "direction": direction,
            "confidence": idx.get("confidence", 0.62),
            "reasons": [f"Geopolitical index {score:.1f}", f"{sector} mapping"],
            "related_events": event_ids,
            "suggested_risk_action": "reduce_or_hedge" if direction == "bearish" and impact >= 50 else "monitor_or_use_as_hedge" if direction == "bullish" else "monitor",
            **evidence,
        })
    return {"impacts": rows, "count": len(rows), "data_quality": idx.get("data_quality", "degraded"), "timestamp": _now(), **evidence}
