from datetime import datetime, timedelta, timezone
import pytest

from backend.compute.event_linked_outcomes import basis_reactions, event_lag_bucket, funding_reactions, regime_path, select_event_points

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_scalar_contract_never_looks_ahead_and_exposes_lag():
    rows = [{"ts": T-timedelta(minutes=1), "v": 1}, {"ts": T+timedelta(minutes=1), "v": 99},
            {"ts": T+timedelta(hours=1, minutes=2), "v": 2}]
    out = select_event_points(rows, T, timestamp_field="ts", value_field="v", now=T+timedelta(days=8))
    assert out["reference"]["value"] == 1
    assert out["horizons"]["1h"]["value"] == 2
    assert out["horizons"]["1h"]["lag_seconds"] == 120


def test_exact_reference_future_and_tolerance_states():
    rows = [{"ts": T, "v": 3}, {"ts": T+timedelta(hours=4), "v": None}, {"ts": T+timedelta(hours=5), "v": 4}]
    out = select_event_points(rows, T, timestamp_field="ts", value_field="v", now=T+timedelta(hours=2), target_lag_seconds=10)
    assert out["reference"]["value"] == 3
    assert out["horizons"]["4h"]["status"] == "not_matured"
    mature = select_event_points(rows, T, timestamp_field="ts", value_field="v", now=T+timedelta(days=8), target_lag_seconds=10)
    assert mature["horizons"]["4h"]["reason"] == "no_observation_within_target_tolerance"


def test_realized_v1_funding_only_delta_sign_and_provenance():
    common = {"venue":"hyperliquid","market":"BTC-PERP","source_id":"hyperliquid","rate_kind":"realized","contract_version":1,
              "interval_seconds":3600,"timestamp_semantics":"provider_settlement","sign_convention":"positive_long_pays_short","annualized_rate":.0876}
    rows = [{**common,"provider_timestamp":T,"normalized_funding_rate":-.0001},
            {**common,"provider_timestamp":T+timedelta(hours=1),"normalized_funding_rate":.0002,"annualized_rate":.1752},
            {**common,"provider_timestamp":T+timedelta(hours=4),"normalized_funding_rate":.0003,"contract_version":0},
            {**common,"provider_timestamp":T+timedelta(hours=4),"normalized_funding_rate":.0004,"rate_kind":"current"}]
    row = funding_reactions(rows,T,now=T+timedelta(days=8))["horizons"]["1h"]
    assert row["delta_bps"] == pytest.approx(3)
    assert row["sign_flip"] is True and row["direction"] == "INCREASED"
    assert row["annualized_delta"] == .0876 and "classification" not in row


def test_basis_is_not_annualized_and_lineage_survives():
    rows=[{"observed_at":T,"basis_bps":-2,"venue":"drift","market":"SOL-PERP","spot_source":"pyth","lineage":{"x":1}},
          {"observed_at":T+timedelta(hours=1),"basis_bps":3,"venue":"drift","market":"SOL-PERP","spot_source":"pyth","lineage":{"x":2}}]
    row=basis_reactions(rows,T,now=T+timedelta(days=8))["horizons"]["1h"]
    assert row["delta_bps"] == 5 and row["sign_flip"]
    assert row["reference_lineage"] == {"x":1} and "annualized_basis_bps" not in row


def test_regime_reference_freshness_and_changed_fields():
    rows=[{"ts":T,"tariff_index":1,"shock_state":"normal","funding_regime":"neutral","vol_regime":"low"},
          {"ts":T+timedelta(hours=1),"tariff_index":1,"shock_state":"high","funding_regime":"neutral","vol_regime":"high"}]
    out=regime_path(rows,T,now=T+timedelta(days=8))
    assert out["horizons"]["1h"]["changed_fields"] == ["shock_state","vol_regime"]
    stale=regime_path([{**rows[0],"ts":T-timedelta(hours=7)}],T,now=T+timedelta(days=8))
    assert stale["reference"] is None


def test_lag_buckets_are_non_overlapping():
    assert [event_lag_bucket(x) for x in (0,3600,3601,14401,86401)] == ["0_to_1h","0_to_1h","1h_to_4h","4h_to_24h","24h_to_7d"]


def test_targeted_repository_contract_source():
    import inspect
    from backend.data.repositories.derivatives_repo import DerivativesRepository
    source=inspect.getsource(DerivativesRepository.get_basis_event_points)
    assert "LIMIT 1" in source and "basis_history" not in source


def test_funding_validation_preserves_422():
    from fastapi import HTTPException
    from backend.api.markets_routes import get_funding
    with pytest.raises(HTTPException) as error:
        get_funding(venue="unsupported")
    assert error.value.status_code == 422
