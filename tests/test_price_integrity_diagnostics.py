from datetime import datetime, timedelta, timezone

from backend.api import markets_routes
from backend.core.price_authority import PriceAuthority
from backend.core.price_validator import PriceValidator
from backend.core.state_keys import price_snapshot_key


class Store:
    def __init__(self):
        self.values = {}

    def get_snapshot(self, key):
        return self.values.get(key)

    def set_snapshot(self, key, value, ttl=None):
        self.values[key] = value

    def check_throttle(self, *args, **kwargs):
        return False


class Bus:
    def emit(self, *args, **kwargs):
        raise AssertionError("diagnostic tests should not emit alerts when throttled")


def validator(**kwargs):
    return PriceValidator(
        state_store=Store(),
        event_bus=Bus(),
        freshness_threshold_seconds=120,
        **kwargs,
    )


def test_three_fresh_agreeing_sources_are_ok_with_quorum_and_median():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator().validate(
        {"pyth": 100.0, "kraken": 100.01, "coingecko": 99.99},
        feed_timestamps={source: now.isoformat() for source in ("pyth", "kraken", "coingecko")},
        now=now,
    )

    assert result["status"] == "OK"
    assert result["quorum_met"] is True
    assert result["usable_source_count"] == 3
    assert result["median_reference_price"] == 100.0
    assert result["max_disagreement_bps"] == 2.0
    assert result["outlier_sources"] == []
    assert result["consensus_is_diagnostic_only"] is True
    assert result["execution_authority_changed"] is False


def test_stale_primary_is_excluded_but_two_fresh_sources_can_establish_integrity():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator().validate(
        {"pyth": 100.0, "kraken": 100.0, "coingecko": 100.01},
        feed_timestamps={
            "pyth": (now - timedelta(minutes=10)).isoformat(),
            "kraken": now.isoformat(),
            "coingecko": now.isoformat(),
        },
        now=now,
    )

    assert result["status"] == "OK"
    assert result["usable_execution_grade_prices"] == {"kraken": 100.0, "coingecko": 100.01}
    assert result["source_diagnostics"]["pyth"]["reason"] == "stale"
    assert result["source_diagnostics"]["pyth"]["usable_for_integrity"] is False
    assert result["selected_priority_context"]["source"] == "pyth"
    assert result["selected_priority_context"]["fresh"] is False
    assert result["selected_priority_context"]["selection_changed"] is False


def test_one_fresh_source_is_unknown_not_healthy():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator().validate(
        {"pyth": 100.0},
        feed_timestamps={"pyth": now.isoformat()},
        now=now,
    )

    assert result["status"] == "UNKNOWN"
    assert result["quorum_met"] is False
    assert result["usable_source_count"] == 1
    assert "Insufficient fresh execution-grade price quorum" in result["reason"]


def test_three_source_disagreement_warns_and_labels_median_outlier():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator(deviation_threshold_bps=50).validate(
        {"pyth": 100.0, "kraken": 100.1, "coingecko": 102.0},
        feed_timestamps={source: now.isoformat() for source in ("pyth", "kraken", "coingecko")},
        now=now,
    )

    assert result["status"] == "WARNING"
    assert result["max_disagreement_bps"] > 50
    assert result["dispersion_bps"] > 50
    assert result["outlier_sources"] == ["coingecko"]
    assert result["source_diagnostics"]["coingecko"]["outlier"] is True


def test_malformed_and_future_timestamps_are_not_fresh():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator().validate(
        {"pyth": 100.0, "kraken": 100.0, "coingecko": 100.0},
        feed_timestamps={
            "pyth": "not-a-timestamp",
            "kraken": (now + timedelta(minutes=1)).isoformat(),
            "coingecko": now.isoformat(),
        },
        now=now,
    )

    assert result["status"] == "UNKNOWN"
    assert result["source_diagnostics"]["pyth"]["reason"] == "missing_or_invalid_timestamp"
    assert result["source_diagnostics"]["kraken"]["reason"] == "future_timestamp"
    assert result["source_diagnostics"]["coingecko"]["usable_for_integrity"] is True


def test_yfinance_never_establishes_integrity_quorum():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = validator().validate(
        {"pyth": 100.0, "yfinance": 100.0},
        feed_timestamps={"pyth": now.isoformat(), "yfinance": now.isoformat()},
        now=now,
    )

    assert result["status"] == "UNKNOWN"
    assert result["usable_source_count"] == 1
    assert result["research_corroboration"]["can_establish_integrity"] is False


def test_price_authority_priority_selection_is_unchanged():
    store = Store()
    now = datetime.now(timezone.utc).isoformat()
    store.values.update({
        price_snapshot_key("pyth", "BTC/USD"): {"price": 100.0, "ts": now},
        price_snapshot_key("kraken", "BTC/USD"): {"price": 99.0, "ts": now},
        price_snapshot_key("coingecko", "BTC/USD"): {"price": 101.0, "ts": now},
    })

    selected = PriceAuthority(state_store=store).get_price("BTC/USD")
    assert selected.found is True
    assert selected.source == "pyth"
    assert selected.price == 100.0


def test_diagnostics_endpoint_is_read_only_and_consensus_does_not_change_selection(monkeypatch):
    now = datetime.now(timezone.utc)

    class FakeValidator:
        def validate_symbol(self, symbol):
            return {
                "symbol": symbol,
                "status": "OK",
                "source_diagnostics": {
                    "pyth": {
                        "fresh": True,
                        "usable_for_integrity": True,
                        "deviation_from_median_bps": 1.0,
                    }
                },
                "usable_source_count": 3,
                "required_quorum": 2,
                "quorum_met": True,
                "consensus_is_diagnostic_only": True,
            }

    class Selected:
        source = "pyth"

        def to_dict(self):
            return {
                "price": 100.0,
                "confidence": 1.0,
                "source": "pyth",
                "ts": now.isoformat(),
                "found": True,
            }

    class FakeAuthority:
        def get_price(self, symbol):
            return Selected()

    monkeypatch.setattr(markets_routes, "_validator", FakeValidator())
    monkeypatch.setattr(markets_routes, "_price_authority", FakeAuthority())

    payload = markets_routes.get_integrity_diagnostics()

    assert set(payload["symbols"]) == {"BTC/USD", "ETH/USD", "SOL/USD"}
    assert payload["status"] == "OK"
    assert payload["read_only"] is True
    assert payload["provider_io"] is False
    assert payload["research_sources_can_establish_integrity"] is False
    assert payload["execution_authority"] == {
        "policy": "priority_first",
        "priority": ["pyth", "kraken", "coingecko"],
        "selection_changed": False,
        "consensus_is_diagnostic_only": True,
    }
    for symbol in payload["symbols"].values():
        assert symbol["selected_execution_price"]["source"] == "pyth"
        assert symbol["selected_execution_price"]["selection_changed"] is False
