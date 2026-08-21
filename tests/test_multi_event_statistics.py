from backend.compute.multi_event_statistics import (
    bootstrap_interval, coverage_summary, descriptive_statistics, filter_overlaps,
    sample_hash, sample_quality, transition_matrix,
)


def test_descriptive_and_robust_statistics_are_deterministic():
    result = descriptive_statistics([1, 2, 3, 4, 100])
    assert result["median"] == 3
    assert result["p25"] == 2 and result["p75"] == 4 and result["iqr"] == 2
    assert result["sample_stddev"] is not None
    assert result["winsorized"]["winsorized_mean"] < result["mean"]
    assert result["bootstrap"] == bootstrap_interval([1, 2, 3, 4, 100])


def test_quality_thresholds_and_tiny_bootstrap():
    assert [sample_quality(n) for n in (0, 4, 5, 19, 20, 49, 50)] == [
        "UNAVAILABLE", "VERY_LOW_SAMPLE", "LOW_SAMPLE", "LOW_SAMPLE",
        "MODERATE_SAMPLE", "MODERATE_SAMPLE", "ESTABLISHED_SAMPLE"]
    assert bootstrap_interval([1, 2, 3, 4])["available"] is False


def test_maturity_overlap_and_missingness_denominator_reconcile():
    rows = [{"status": "available"}, {"status": "not_matured", "reason": "horizon_not_matured"},
            {"status": "unavailable", "reason": "overlap_excluded"},
            {"status": "unavailable", "reason": "event_predates_dataset"}]
    result = coverage_summary(rows)
    assert result == {**result, "candidate_n": 4, "matured_n": 3, "observed_n": 1,
                      "not_matured_n": 1, "missing_n": 1, "overlap_excluded_n": 1,
                      "coverage_denominator_n": 2, "coverage_rate": .5}


def test_overlap_is_chronological_horizon_specific_and_hash_is_stable():
    events = [{"event_id": "b", "event_timestamp": "2025-01-01T01:30:00Z"},
              {"event_id": "a", "event_timestamp": "2025-01-01T01:00:00Z"}]
    assert filter_overlaps(events, horizon_seconds=3600)["overlap_excluded_event_ids"] == ["b"]
    assert filter_overlaps(events, horizon_seconds=1200)["overlap_excluded_count"] == 0
    args = dict(event_ids=["a", "b"], filters={"type": "x"}, horizons={"1h": 3600})
    assert sample_hash(**args) == sample_hash(**args)
    assert sample_hash(**args) != sample_hash(**{**args, "event_ids": ["b", "a"]})


def test_transition_rates_use_origin_denominator():
    result = transition_matrix([("normal", "high"), ("normal", "normal"), ("high", "high")])
    assert result["changed_count"] == 1 and result["changed_rate"] == 1 / 3
    assert next(c for c in result["cells"] if c["from"] == "normal" and c["to"] == "high")["rate"] == .5
