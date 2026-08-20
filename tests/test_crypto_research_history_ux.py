from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "frontend/assets/api.js").read_text(encoding="utf-8")
APP = (ROOT / "frontend/assets/app.js").read_text(encoding="utf-8")
UI = (ROOT / "frontend/assets/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend/index.html").read_text(encoding="utf-8")


def test_coverage_endpoint_is_read_only_and_failure_is_isolated():
    helper = API[API.index("getResearchHistoryCoverage"):API.index("getMarketHistory", API.index("getResearchHistoryCoverage"))]
    assert "/api/markets/research-history/coverage" in helper
    assert "URLSearchParams" in helper
    assert "POST" not in helper and "PUT" not in helper
    assert "Promise.allSettled" in APP
    assert "API.getResearchHistoryCoverage()" in APP
    assert "researchHistoryCoverage.status === 'fulfilled'" in APP


def test_markets_coverage_renders_raw_measurements_and_safety_boundary():
    assert 'id="crypto-research-history-panel"' in HTML
    for token in ("BTC/USD", "ETH/USD", "SOL/USD", "coverage_ratio", "observed_observation_count",
                  "expected_observation_count", "max_gap_seconds", "last_observation_ts", "age_seconds",
                  "GOOD COVERAGE", "PARTIAL", "DEGRADED", "Research history coverage unavailable",
                  "RESEARCH ONLY", "NOT EXECUTION ELIGIBLE"):
        assert token in UI
    assert "observed > 0 && Number.isFinite(ratio)" in UI


def test_reaction_history_provenance_is_per_asset_and_missing_safe():
    for token in ("MARKET HISTORY USED", "history_metadata", "provider_status", "durable_research_market_bars",
                  "DURABLE LOCAL", "yahoo_on_demand", "YAHOO ON-DEMAND", "PERSISTED", "NOT PERSISTED",
                  "Market history provenance unavailable", "EVENT STUDY — NOT CAUSAL ATTRIBUTION"):
        assert token in UI
    assert "['BTC', 'ETH', 'SOL'].map" in UI
    assert "status.found !== false" in UI
