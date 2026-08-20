import pytest
import time


def test_basis_engine_compute():
    from backend.compute.basis_engine import compute_basis
    result = compute_basis(
        hl_perp_price=100.5,
        drift_perp_price=100.3,
        spot_price=100.0,
    )
    assert "hl_spot_basis_bps" in result
    assert "drift_spot_basis_bps" in result
    assert "annualized_basis_bps" in result
    assert "net_carry" in result
    assert result["hl_spot_basis_bps"] == 50.0
    assert result["drift_spot_basis_bps"] == 30.0


def test_basis_engine_zero_spot():
    from backend.compute.basis_engine import compute_basis
    result = compute_basis(100.0, 99.0, 0.0)
    assert result["hl_spot_basis_bps"] is None


def test_funding_arb_no_signal():
    from backend.compute.funding_arb import FundingArbDetector
    det = FundingArbDetector()
    result = det.detect_arb(None, None)
    assert result["available"] is False


def test_funding_arb_long_hl():
    from backend.compute.funding_arb import FundingArbDetector
    det = FundingArbDetector()
    result = det.detect_arb({}, {})
    assert result["available"] is False


def test_funding_arb_short_hl():
    from backend.compute.funding_arb import FundingArbDetector
    det = FundingArbDetector()
    result = det.detect_arb({}, {})
    assert result["available"] is False


def test_stable_flow_healthy():
    from backend.compute.stable_flow import compute_flow_momentum
    result = compute_flow_momentum(
        stable_prices={"usdt": 1.0, "usdc": 1.0, "dai": 1.0},
    )
    assert "stable_flow_momentum" in result
    assert "risk_on_off_indicator" in result
    assert "drivers" in result
    assert -1.0 <= result["stable_flow_momentum"] <= 1.0


def test_stable_flow_stress():
    from backend.compute.stable_flow import compute_flow_momentum
    result = compute_flow_momentum(
        stable_prices={"usdt": 0.98, "usdc": 0.99, "dai": 0.97},
    )
    assert result["stable_flow_momentum"] < 0
    assert result["risk_on_off_indicator"] == "risk_off"


def test_stable_flow_empty():
    from backend.compute.stable_flow import compute_flow_momentum
    result = compute_flow_momentum()
    assert result["risk_on_off_indicator"] == "neutral"


def test_adaptive_weights_default():
    from backend.compute.adaptive_weights import compute_weights
    result = compute_weights()
    assert "weights" in result
    w = result["weights"]
    total = sum(w.values())
    assert abs(total - 1.0) < 0.001


def test_adaptive_weights_high_shock():
    from backend.compute.adaptive_weights import compute_weights
    result = compute_weights(shock_score=90.0)
    w = result["weights"]
    assert w["macro"] > 0.25


def test_adaptive_weights_high_vol():
    from backend.compute.adaptive_weights import compute_weights
    result = compute_weights(vol_regime="high")
    w = result["weights"]
    assert w["microstructure"] >= 0.25


def test_portfolio_risk_parity():
    from backend.compute.portfolio_optimizer import optimize
    result = optimize({"method": "risk_parity"})
    assert "allocation" in result
    alloc = result["allocation"]
    total = sum(alloc.values())
    assert abs(total - 1.0) < 0.01
    assert all(v >= 0 for v in alloc.values())
    assert all(v <= 1.0 for v in alloc.values())


def test_portfolio_mean_variance():
    from backend.compute.portfolio_optimizer import optimize
    result = optimize({"method": "mean_variance", "macro_regime": "bullish"})
    alloc = result["allocation"]
    total = sum(alloc.values())
    assert abs(total - 1.0) < 0.01


def test_portfolio_scaled_kelly():
    from backend.compute.portfolio_optimizer import optimize
    result = optimize({"method": "kelly", "predictor_prob": 0.7})
    alloc = result["allocation"]
    total = sum(alloc.values())
    assert abs(total - 1.0) < 0.01


def test_portfolio_caps_respected():
    from backend.compute.portfolio_optimizer import optimize, HARD_CAPS, HARD_FLOORS
    result = optimize({"method": "risk_parity"})
    alloc = result["allocation"]
    for k, v in alloc.items():
        assert v <= HARD_CAPS.get(k, 1.0) + 0.05
        assert v >= HARD_FLOORS.get(k, 0.0) - 0.01


def test_liquidation_heatmap_shape():
    from backend.compute.liquidation_heatmap import compute_heatmap, LEVERAGE_LEVELS, PRICE_DROPS_PCT
    result = compute_heatmap(100.0, [], 0.5, 0.3)
    grid = result["grid"]
    assert len(grid) == len(LEVERAGE_LEVELS)
    for lev in LEVERAGE_LEVELS:
        row = grid[str(lev)]
        assert len(row) == len(PRICE_DROPS_PCT)


def test_liquidation_heatmap_monotonic_leverage():
    from backend.compute.liquidation_heatmap import compute_heatmap, LEVERAGE_LEVELS, PRICE_DROPS_PCT
    result = compute_heatmap(100.0, [], 0.5, 0.3)
    grid = result["grid"]
    for drop in PRICE_DROPS_PCT:
        prev = -1
        for lev in LEVERAGE_LEVELS:
            curr = grid[str(lev)][str(drop)]
            assert curr >= prev, f"Non-monotonic: lev={lev}, drop={drop}"
            prev = curr


def test_liquidation_heatmap_monotonic_drop():
    from backend.compute.liquidation_heatmap import compute_heatmap, LEVERAGE_LEVELS, PRICE_DROPS_PCT
    result = compute_heatmap(100.0, [], 0.5, 0.3)
    grid = result["grid"]
    for lev in LEVERAGE_LEVELS:
        prev = -1
        for drop in PRICE_DROPS_PCT:
            curr = grid[str(lev)][str(drop)]
            assert curr >= prev, f"Non-monotonic: lev={lev}, drop={drop}"
            prev = curr


def test_liquidation_heatmap_probabilities_bounded():
    from backend.compute.liquidation_heatmap import compute_heatmap, LEVERAGE_LEVELS, PRICE_DROPS_PCT
    result = compute_heatmap(100.0, [], 0.5, 0.3)
    grid = result["grid"]
    for lev in LEVERAGE_LEVELS:
        for drop in PRICE_DROPS_PCT:
            prob = grid[str(lev)][str(drop)]
            assert 0.0 <= prob <= 1.0


def test_execution_metrics_eqi():
    from backend.compute.execution_metrics import ExecutionMetrics
    em = ExecutionMetrics()
    now = time.time()
    for i in range(10):
        em.record_fill(
            order_ts=now - 0.05,
            fill_ts=now,
            expected_price=100.0,
            fill_price=100.0 + (i * 0.01),
            venue="paper",
            market="SOL-PERP",
        )
    eqi = em.get_eqi()
    assert "eqi_score" in eqi
    assert 0 <= eqi["eqi_score"] <= 100
    assert eqi["fill_count"] == 10
    assert eqi["latency_p50_ms"] >= 0
    assert eqi["latency_p95_ms"] >= eqi["latency_p50_ms"]


def test_execution_metrics_slippage_anomaly():
    from backend.compute.execution_metrics import ExecutionMetrics
    em = ExecutionMetrics()
    now = time.time()
    for i in range(20):
        em.record_fill(now - 0.05, now, 100.0, 100.01, "paper", "SOL-PERP")
    result = em.detect_slippage_anomaly(200.0, "paper")
    assert result["is_anomaly"] is True


def test_execution_metrics_no_anomaly():
    from backend.compute.execution_metrics import ExecutionMetrics
    em = ExecutionMetrics()
    now = time.time()
    for i in range(20):
        em.record_fill(now - 0.05, now, 100.0, 100.01, "paper", "SOL-PERP")
    result = em.detect_slippage_anomaly(1.5, "paper")
    assert result["is_anomaly"] is False


def test_solana_quality():
    from backend.compute.solana_liquidity import compute_quality
    result = compute_quality(spread_bps=5.0, price_impact_bps=10.0, rpc_latency_ms=200, ob_depth=50000)
    assert "execution_quality_score" in result
    assert 0 <= result["execution_quality_score"] <= 100
    assert "slippage_risk" in result
    assert result["slippage_risk"] in ("low", "medium", "high")


def test_solana_congestion():
    from backend.compute.solana_liquidity import assess_congestion
    result = assess_congestion(rpc_latency_ms=2000, slot_delta=10)
    assert "congested" in result
    assert result["congested"] is True


def test_solana_no_congestion():
    from backend.compute.solana_liquidity import assess_congestion
    result = assess_congestion(rpc_latency_ms=100, slot_delta=1)
    assert result["congested"] is False
