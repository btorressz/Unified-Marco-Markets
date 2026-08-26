from pathlib import Path


UI = Path("frontend/assets/reaction-statistics-ui.js").read_text()
INDEX = Path("frontend/index.html").read_text()
LEGACY_UI = Path("frontend/assets/ui.js").read_text()


def test_multi_event_panel_and_headline_matrices_remain_wired():
    assert 'id="geo-reaction-statistics-panel"' in INDEX
    assert "ReactionStatisticsUI.render(panel, data, escapeHtml)" in LEGACY_UI
    assert "HEADLINE PRICE REACTIONS · MEDIAN" in UI
    assert "REALIZED FUNDING REACTIONS · MEDIAN Δ BPS" in UI
    assert "PERPETUAL BASIS REACTIONS · MEDIAN Δ BPS" in UI


def test_sample_truth_and_strata_are_structured():
    for token in (
        "Candidate", "Included", "Excluded", "HETEROGENEOUS EVENT-TIME BASIS",
        "Combined headline statistics are intentionally suppressed",
        "results_by_event_time_basis", "results_by_event_type", "results_by_event_family",
        "SHOWING ${number(meta.returned_group_count)} OF ${number(meta.group_count)} GROUPS",
        "VERY LOW SAMPLE", "LOW SAMPLE", "UNAVAILABLE",
    ):
        assert token in UI


def test_derivative_regime_and_decision_details_are_exposed():
    for token in (
        "increased_count", "decreased_count", "sign_flip_rate",
        "premium_to_discount_count", "discount_to_premium_count",
        "transition_observed_n", "coverage_rate", "overlap_excluded_count",
        "ALLOW", "BLOCK", "classification_counts", "results_by_link_type",
        "results_by_regime_signature", "DECISION EVENT TYPE RESULTS",
        "DECISION EVENT FAMILY RESULTS", "DECISION COHORT TRUNCATED",
        "EXPLICIT RECORDED LINK", "TEMPORAL PROXIMITY",
        "counterfactual subsequent market movement",
    ):
        assert token in UI


def test_auditability_methodology_and_noncausal_boundaries_are_visible():
    for token in (
        "SAMPLE FUNNEL · ATTRITION · MISSINGNESS · OVERLAP",
        "DATA QUERY INTEGRITY", "QUERY TRUNCATED", "Bootstrap method",
        "Bootstrap seed", "Bootstrap iterations", "Winsorization policy",
        "Significance testing", "FALSE — NOT PERFORMED", "DESCRIPTIVE BOOTSTRAP INTERVAL",
        "Apparent patterns may arise by chance", "NON-CAUSAL", "RESEARCH ONLY",
    ):
        assert token in UI
    assert "JSON.stringify" not in UI


def test_dynamic_provider_group_reason_and_error_values_are_escaped():
    assert "escape(name)" in UI
    assert "escape(row.error || '--')" in UI
    assert "label(group.reason || 'statistics unavailable', escape)" in UI
    assert "escape(study.sample_hash || '--')" in UI
    assert '<script src="/frontend/assets/reaction-statistics-ui.js"></script>' in INDEX


def test_no_new_top_level_statistics_tab():
    assert 'id="tab-statistics"' not in INDEX
    assert 'data-tab="statistics"' not in INDEX
