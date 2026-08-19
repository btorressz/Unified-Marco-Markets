from backend.compute.conflict_escalation import score_conflicts, conflict_market_impact
from backend.compute.geopolitical_evidence import authoritative_evidence, match_evidence, proxy_evidence
from backend.ingest.quality import authoritative_evidence_envelope
from backend.compute.geopolitical_market_impact import estimate_market_impact
from backend.compute.geopolitical_risk import compute_geopolitical_index, build_geopolitical_events
from backend.compute.sanctions_risk import score_sanctions
from backend.compute.shipping_energy_risk import score_chokepoints


def _gdelt():
    return {
        "shock_score": 1.2,
        "evidence_count": 3,
        "evidence_documents": [
            {
                "evidence_id": "e1",
                "title": "Shipping tensions rise in the Red Sea near Yemen",
                "url": "https://example.com/red-sea",
                "domain": "example.com",
                "sourcecountry": "United States",
                "seendate": "20260818T120000Z",
                "tone_avg": -2.0,
            },
            {
                "evidence_id": "e2",
                "title": "New discussion of China semiconductor export controls",
                "url": "https://example.com/china-controls",
                "domain": "example.com",
                "sourcecountry": "United Kingdom",
                "seendate": "20260818T110000Z",
                "tone_avg": -1.0,
            },
            {
                "evidence_id": "e3",
                "title": "Unrelated macro headline",
                "url": "https://example.com/macro",
                "domain": "example.com",
                "sourcecountry": "Canada",
                "seendate": "20260818T100000Z",
                "tone_avg": 0.0,
            },
        ],
    }


def test_literal_evidence_matching_is_bounded_and_non_authoritative():
    matches = match_evidence(_gdelt(), terms=["red sea", "suez"])
    assert [row["evidence_id"] for row in matches] == ["e1"]
    evidence = proxy_evidence(gdelt=_gdelt(), terms=["red sea"], static_mapping="chokepoint:red-sea")
    assert evidence["claim_type"] == "evidence_supported_proxy"
    assert evidence["observed"] is False
    assert evidence["proxy"] is True
    assert evidence["authoritative_evidence"] is False
    assert evidence["evidence_count"] == 1


def test_specific_conflict_and_chokepoint_outputs_never_become_observed_from_gdelt_news():
    conflicts = score_conflicts(_gdelt())
    red_sea = next(row for row in conflicts["hotspots"] if row["region"] == "Red Sea / Suez")
    assert red_sea["claim_type"] == "evidence_supported_proxy"
    assert red_sea["observed"] is False
    assert red_sea["evidence_count"] == 1

    shipping = score_chokepoints(_gdelt())
    red_sea_choke = next(row for row in shipping["chokepoints"] if row["name"] == "Red Sea / Suez Canal")
    assert red_sea_choke["claim_type"] == "evidence_supported_proxy"
    assert red_sea_choke["observed"] is False
    assert "closure" in " ".join(red_sea_choke["limitations"]).lower()


def test_sanctions_news_support_does_not_claim_authoritative_sanction():
    sanctions = score_sanctions(gdelt=_gdelt(), ofac=None, wits={"tariff_pressure": 20})
    china = next(row for row in sanctions["programs"] if row["program"] == "China export controls")
    assert china["claim_type"] == "evidence_supported_proxy"
    assert china["observed"] is False
    assert china["authoritative_evidence"] is False
    assert sanctions["new_sanctions"] is False
    assert sanctions["provider_status"]["ofac_public_download"] == "not_configured"


def test_market_impact_is_expected_not_realized_or_causal():
    impacts = estimate_market_impact({"overall_score": 70, "confidence": 0.6}, [{"event_id": "evt-1"}])
    assert impacts["claim_type"] == "expected_market_impact"
    assert impacts["observed_market_reaction"] is False
    assert impacts["causal_claim"] is False
    assert impacts["impacts"]
    assert all(row["claim_type"] == "expected_market_impact" for row in impacts["impacts"])

    conflict_impacts = conflict_market_impact(score_conflicts(_gdelt()))
    assert conflict_impacts["observed_market_reaction"] is False
    assert conflict_impacts["causal_claim"] is False


def test_only_valid_v2_records_are_authoritative_observed_evidence():
    record = authoritative_evidence_envelope(
        source="test", source_id="official_test", authority="Test Authority",
        jurisdiction=None, dataset="Test", observation={"value": 1},
        source_record_id="1", retrieved_at="2026-08-19T00:00:00+00:00",
    )
    assert authoritative_evidence(record, source_id="official_test") == {
        "claim_type": "observed_evidence", "observed": True, "proxy": False,
        "scenario": False, "authoritative_evidence": True,
        "evidence_basis": "normalized_authoritative_provider_record",
    }
    assert authoritative_evidence({"source": "OFAC"})["authoritative_evidence"] is False


def test_composite_index_and_normalized_events_preserve_proxy_boundary():
    index = compute_geopolitical_index({
        "gdelt": _gdelt(),
        "wits": {"tariff_pressure": 20, "available": True, "synthetic": False, "fallback_used": False},
    })
    assert index["claim_type"] == "composite_research_proxy"
    assert index["observed"] is False
    assert index["evidence_count"] == 3

    events = build_geopolitical_events(index)
    assert events["events"]
    assert all(event.get("observed") is False for event in events["events"])
    assert all(event.get("claim_type") in {"proxy", "evidence_supported_proxy"} for event in events["events"])
