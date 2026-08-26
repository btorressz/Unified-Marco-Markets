from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "assets" / "price-integrity-ui.js"
REACTION_LOADER = ROOT / "frontend" / "assets" / "reaction-statistics-ui.js"
INDEX = ROOT / "frontend" / "index.html"


def test_price_integrity_diagnostics_module_contract():
    text = MODULE.read_text()
    assert "Canonical Price Integrity · Freshness · Consensus Diagnostics" in text
    assert "DIAGNOSTIC CONSENSUS ONLY — EXECUTION PRICE SELECTION UNCHANGED" in text
    assert "CONSENSUS DIAGNOSTIC ONLY" in text
    assert "SELECTION UNCHANGED" in text
    assert "YAHOO CANNOT ESTABLISH INTEGRITY" in text
    assert "BTC/USD" in text and "ETH/USD" in text and "SOL/USD" in text
    assert "usable_source_count" in text
    assert "required_quorum" in text
    assert "median_reference_price" in text
    assert "max_disagreement_bps" in text
    assert "dispersion_bps" in text
    assert "outlier_sources" in text
    assert "selected_execution_price" in text
    assert "age_seconds" in text
    assert "deviation_from_median_bps" in text
    assert "usable_for_integrity" in text
    assert "provider_io" in text
    assert "row.reason" in text
    assert "escapeHtml" in text


def test_existing_frontend_extension_loads_diagnostics_without_new_tab():
    loader = REACTION_LOADER.read_text()
    index = INDEX.read_text()

    assert "import('/frontend/assets/price-integrity-ui.js')" in loader
    assert "/api/markets/integrity/diagnostics" in MODULE.read_text()
    assert "price-integrity-diagnostics-panel" in MODULE.read_text()
    assert 'data-tab="price-integrity"' not in index


def test_frontend_diagnostics_do_not_replace_execution_authority():
    text = MODULE.read_text()
    assert "priority" in text.lower()
    assert "Median, quorum, disagreement and outlier measurements explain source quality" in text
    assert "do not replace the selected execution price" in text
    assert "consensus execution price" not in text.lower()
    assert "switch execution source" not in text.lower()


def test_missing_values_render_unavailable_not_zero():
    text = MODULE.read_text()
    assert "return '--'" in text
    assert "UNAVAILABLE" in text
    assert "0.00" not in text
