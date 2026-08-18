from backend.compute.macro_predictor import MacroPredictor


class FakeStateStore:
    def __init__(self, snapshots=None):
        self.snapshots = dict(snapshots or {})

    def get_snapshot(self, key):
        return self.snapshots.get(key)

    def set_snapshot(self, key, payload, ttl=None):
        self.snapshots[key] = payload
        return True


def test_legacy_unqualified_health_cache_is_rebuilt_as_unavailable(monkeypatch):
    import backend.api.stablecoin_routes as routes

    legacy = {
        symbol: {"price": 1.0, "depeg_bps": 0.0, "status": "ok"}
        for symbol in ("USDC", "USDT", "DAI")
    }
    store = FakeStateStore({"stablecoin:health:latest": legacy})
    monkeypatch.setattr(routes, "_store", store)

    result = routes.get_health()
    for row in result["health"].values():
        assert row["available"] is False
        assert row["status"] == "unavailable"
        assert row["stress"] is None
        assert row["peg_break_probability"] is None
    assert result["alerts"] == []


def test_predict_features_use_neutral_stablecoin_value_when_observations_missing(monkeypatch):
    import backend.api.predict_routes as routes

    store = FakeStateStore({
        "stablecoin:health:latest": {
            "USDC": {"available": False, "status": "unavailable", "quality": {"observed": False}},
            "USDT": {"available": False, "status": "unavailable", "quality": {"observed": False}},
            "DAI": {"available": False, "status": "unavailable", "quality": {"observed": False}},
        }
    })
    monkeypatch.setattr(routes, "_store", store)
    features = routes._build_features("SOL")
    assert features["stablecoin_health_score"] == 0.5
    assert features["stablecoin_data_available"] is False
    assert features["stablecoin_observation_count"] == 0


def test_macro_predictor_missing_stablecoin_feature_has_zero_contribution():
    predictor = MacroPredictor()
    result = predictor.predict({})
    assert result["feature_contributions"]["stablecoin_health"] == 0.0
