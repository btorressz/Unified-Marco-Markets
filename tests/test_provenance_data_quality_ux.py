from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "frontend/assets/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
DECISIONS = (ROOT / "frontend/assets/decision_outcomes.js").read_text(encoding="utf-8")


def test_unavailable_stablecoins_are_classified_before_depeg_math():
    assert "const available = s.available === true" in UI
    assert "const depeg = available ? Math.abs(Number(s.depeg_bps)) : null" in UI
    assert "Math.abs(s.depeg_bps || 0)" not in UI
    assert "No observed Pyth/Kraken price available" in UI
    assert '<div class="metric-value green">$1.0000</div>' not in HTML


def test_shared_vocabulary_preserves_claim_boundaries():
    for label in ("OBSERVED", "EVIDENCE-SUPPORTED PROXY", "AUTHORITATIVE", "NON-AUTHORITATIVE", "RESEARCH ONLY", "EXPECTED IMPACT", "UNAVAILABLE"):
        assert label in UI
    assert "NOT OBSERVED" in UI
    assert "NO CAUSAL CLAIM" in UI
    assert "synthetic" in UI and "fallback_used" in UI


def test_wits_structured_provenance_and_raw_lineage_remain_inspectable():
    for field in ("Reporter", "Partner", "Product", "Year", "Indicator", "Observation key", "Raw tariff observation"):
        assert field in UI
    assert "normalized Tariff Index" in UI
    assert "Raw JSON lineage" in UI
    assert "Structured observation metadata" in UI


def test_registry_status_join_is_source_id_deterministic_and_missing_safe():
    assert "new Map(ingestionStatus.map(row => [row.source_id, row]))" in UI
    assert "statusById.get(source.source_id) || {}" in UI


def test_cohort_governance_counts_and_versions_are_visible():
    for token in ("stale_counts", "unavailable_counts", "recorded_decision_counts", "Reconstructed", "Freshness-policy version", "cohort_definition_version"):
        assert token in DECISIONS
