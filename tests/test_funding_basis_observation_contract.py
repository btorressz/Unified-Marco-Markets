from datetime import datetime, timedelta, timezone

import pytest

from backend.compute.basis_engine import compute_basis_observation
from backend.compute.funding_arb import FundingArbDetector
from backend.core.derivatives_observations import FundingObservation, annualize_rate
from backend.core.state_keys import funding_snapshot_candidates, funding_snapshot_key


def observation(venue, rate, now=None, interval=3600):
    now = now or datetime.now(timezone.utc)
    return FundingObservation.symmetric(source_id=f"{venue}_test", venue=venue,
        market="SOL-PERP", rate_kind="realized", raw_rate=rate,
        normalized_rate=rate, interval_seconds=interval, provider_timestamp=now,
        timestamp_semantics="provider_funding_settlement_time").model_dump(mode="python")


def test_interval_aware_annualization():
    assert annualize_rate(.0001, 3600) == pytest.approx(.8766)
    assert annualize_rate(.0001, 28800) == pytest.approx(.109575)
    with pytest.raises(ValueError): annualize_rate(.1, 0)


@pytest.mark.parametrize("rate,long_side,short_side", [(0.0001,-0.0001,0.0001),(-0.0001,0.0001,-0.0001)])
def test_hyperliquid_symmetric_sign_contract(rate, long_side, short_side):
    obs = observation("hyperliquid", rate)
    assert obs["interval_seconds"] == 3600
    assert obs["long_cashflow_rate"] == long_side
    assert obs["short_cashflow_rate"] == short_side


def test_canonical_and_legacy_keys():
    assert funding_snapshot_key("hyperliquid", "BTC-PERP") == "funding:hyperliquid:BTC_PERP"
    assert funding_snapshot_candidates("drift", "SOL-PERP") == ("funding:drift:SOL_PERP", "funding:drift:SOL-PERP")


def test_funding_arb_requires_v1_and_uses_side_cashflows():
    now = datetime.now(timezone.utc)
    missing = FundingArbDetector().detect_arb(observation("hyperliquid", .001, now), None, now=now)
    assert missing["available"] is False and missing["expected_net_carry"] is None
    result = FundingArbDetector().detect_arb(observation("hyperliquid", .001, now), observation("drift", -.001, now), now=now)
    assert result["direction"] == "short_hl_long_drift"
    assert result["expected_net_carry"] > 0


def test_basis_formula_no_perpetual_annualization():
    now = datetime.now(timezone.utc)
    result = compute_basis_observation(symbol="BTC/USD", venue="hyperliquid", market="BTC-PERP",
        spot_source="pyth", spot_price=100, spot_ts=now, perp_price=101, perp_ts=now, now=now)
    assert result["basis_bps"] == pytest.approx(100)
    assert result["annualized_basis_bps"] is None
    assert result["annualization_defined"] is False


def test_basis_missing_stale_and_skew_are_unavailable():
    now = datetime.now(timezone.utc)
    missing = compute_basis_observation(symbol="ETH/USD", venue="hyperliquid", market="ETH-PERP",
        spot_source="none", spot_price=None, spot_ts=None, perp_price=100, perp_ts=now, now=now)
    assert missing["available"] is False and missing["basis_bps"] is None
    stale = compute_basis_observation(symbol="SOL/USD", venue="hyperliquid", market="SOL-PERP",
        spot_source="pyth", spot_price=100, spot_ts=now-timedelta(minutes=10),
        perp_price=101, perp_ts=now, now=now)
    assert stale["available"] is False
    assert "timestamp_skew_exceeded" in stale["reasons"]
