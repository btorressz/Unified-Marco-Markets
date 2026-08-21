import pytest
from fastapi import HTTPException

import backend.api.geopolitical_routes as routes


class FakeStatisticsService:
    def __init__(self):
        self.kwargs = None

    def build(self, **kwargs):
        self.kwargs = kwargs
        return {
            "study": {
                "contract_version": "multi_event_stats_v1",
                "causal_claim": False,
                "research_only": True,
                "persisted": False,
                "orders_submitted": 0,
            },
            "filters": kwargs,
        }


def test_statistics_route_forwards_bounded_filters_without_mutation(monkeypatch):
    fake = FakeStatisticsService()
    monkeypatch.setattr(routes, "_reaction_statistics", fake)

    result = routes.reaction_lab_statistics(
        event_family="sanctions",
        event_type="OFAC_SANCTION_ADDED",
        source="ofac_sdn",
        claim_type="observed_evidence",
        event_time_basis="provider_change_detected_at_retrieval",
        start_ts="2026-08-01T00:00:00Z",
        end_ts="2026-08-10T00:00:00Z",
        limit=25,
        include_decisions=False,
    )

    assert result["study"]["causal_claim"] is False
    assert result["study"]["persisted"] is False
    assert result["study"]["orders_submitted"] == 0
    assert fake.kwargs["event_family"] == "sanctions"
    assert fake.kwargs["event_type"] == "OFAC_SANCTION_ADDED"
    assert fake.kwargs["source_id"] == "ofac_sdn"
    assert fake.kwargs["event_time_basis"] == "provider_change_detected_at_retrieval"
    assert fake.kwargs["limit"] == 25
    assert fake.kwargs["include_decisions"] is False


def test_statistics_route_rejects_unknown_overlap_policy_before_service_call(monkeypatch):
    fake = FakeStatisticsService()
    monkeypatch.setattr(routes, "_reaction_statistics", fake)

    with pytest.raises(HTTPException) as exc:
        routes.reaction_lab_statistics(overlap_policy="unsafe_overlap")

    assert exc.value.status_code == 422
    assert fake.kwargs is None
