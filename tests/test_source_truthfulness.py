import asyncio

import pandas as pd

from backend.compute.geopolitical_risk import compute_geopolitical_index
from backend.compute.macro_events import build_macro_events
from backend.ingest.provenance import IngestRunContext
from backend.ingest.quality import is_observed_snapshot, observation_quality
from backend.ingest.wits_ingest import WITSIngestor


class FakeStateStore:
    def __init__(self, snapshots=None):
        self.snapshots = dict(snapshots or {})
        self.writes = []

    def get_snapshot(self, key):
        return self.snapshots.get(key)

    def set_snapshot(self, key, payload, ttl=None):
        self.snapshots[key] = payload
        self.writes.append((key, payload, ttl))
        return True


class FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, event_type, source, payload):
        self.events.append((event_type, source, payload))
        return "event-1"


class FakeIngestRepo:
    def __init__(self):
        self.observations = []
        self.provenance = []

    def record_source_observation(self, **kwargs):
        self.observations.append(kwargs)
        return {"id": len(self.observations)}

    def record_provenance(self, *args, **kwargs):
        self.provenance.append((args, kwargs))
        return {"id": len(self.provenance)}


def test_observation_quality_never_calls_missing_or_synthetic_data_observed():
    missing = observation_quality(
        source="test", source_id="test", available=False, authoritative=True,
    )
    synthetic = observation_quality(
        source="test", source_id="test", available=True, authoritative=True, synthetic=True,
    )
    observed = observation_quality(
        source="test", source_id="test", available=True, authoritative=True,
    )
    assert missing["observed"] is False
    assert missing["degraded"] is True
    assert synthetic["observed"] is False
    assert synthetic["degraded"] is True
    assert observed["observed"] is True
    assert is_observed_snapshot({"quality": observed}) is True
    assert is_observed_snapshot({"fallback_used": True, "tariff_pressure": 99}) is False


def test_wits_sdmx_parser_preserves_dimension_coordinates():
    ingestor = WITSIngestor(
        state_store=FakeStateStore(), event_bus=FakeEventBus(), ingest_repo=FakeIngestRepo(),
    )
    payload = {
        "structure": {
            "dimensions": {
                "observation": [
                    {"id": "REPORTER", "values": [{"id": "840", "name": "United States"}]},
                    {"id": "PARTNER", "values": [{"id": "156", "name": "China"}]},
                    {"id": "PRODUCT", "values": [{"id": "UNCTAD-SoP4", "name": "Capital goods"}]},
                    {"id": "TIME_PERIOD", "values": [{"id": "2024"}, {"id": "2025"}]},
                    {"id": "INDICATOR", "values": [{"id": "AHS-SMPL-AVRG"}]},
                ]
            }
        },
        "dataSets": [{"observations": {"0:0:0:1:0": [7.25]}}],
    }
    rows = ingestor._parse_response(payload, reporter="840", partner="156", product="UNCTAD-SoP4")
    assert rows == [{
        "reporter": "840",
        "partner": "156",
        "product": "UNCTAD-SoP4",
        "year": 2025,
        "indicator": "AHS-SMPL-AVRG",
        "tariff_rate": 7.25,
        "observation_key": "0:0:0:1:0",
        "dimensions": {
            "REPORTER": {"id": "840", "name": "United States"},
            "PARTNER": {"id": "156", "name": "China"},
            "PRODUCT": {"id": "UNCTAD-SoP4", "name": "Capital goods"},
            "TIME_PERIOD": {"id": "2025", "name": None},
            "INDICATOR": {"id": "AHS-SMPL-AVRG", "name": None},
        },
    }]


def test_wits_aggregate_uses_only_observed_batches_and_preserves_last_when_none():
    store = FakeStateStore({"wits:tariff:aggregate": {"tariff_pressure": 12.0, "observed": True}})
    repo = FakeIngestRepo()
    ingestor = WITSIngestor(state_store=store, event_bus=FakeEventBus(), ingest_repo=repo)
    context = IngestRunContext("wits_tariffs", run_id="run-1")

    observed = pd.DataFrame([{"tariff_rate": 10.0}, {"tariff_rate": 20.0}])
    observed.attrs["observed"] = True
    missing = pd.DataFrame(columns=["tariff_rate"])
    missing.attrs["observed"] = False

    payload = ingestor._store_aggregate_freshness([observed, missing], run_context=context)
    assert payload["tariff_pressure"] == 15.0
    assert payload["records_returned"] == 2
    assert payload["fallback_used"] is False
    assert payload["synthetic"] is False
    assert payload["data_quality"] == "partial_provider"

    store.writes.clear()
    result = ingestor._store_aggregate_freshness([missing], run_context=context)
    assert result is None
    assert store.writes == []


def test_wits_provider_failure_returns_empty_not_sample(monkeypatch):
    class FailingResponse:
        def raise_for_status(self):
            raise RuntimeError("provider down")

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return FailingResponse()

    monkeypatch.setattr("backend.ingest.wits_ingest.httpx.AsyncClient", lambda *args, **kwargs: FailingClient())
    context = IngestRunContext("wits_tariffs", run_id="run-1")
    ingestor = WITSIngestor(
        state_store=FakeStateStore(), event_bus=FakeEventBus(), ingest_repo=FakeIngestRepo(),
    )
    result = asyncio.run(ingestor.fetch_tariff_data(reporter="840", partner="CHN", product="Capital", run_context=context))
    assert result.empty
    assert result.attrs["observed"] is False
    assert result.attrs["reason"] == "provider_request_failure"
    assert context.records_received == 0


def test_legacy_fallback_wits_is_not_used_as_observed_macro_or_geo_evidence():
    fallback_wits = {
        "tariff_pressure": 99.0,
        "value": 99.0,
        "fallback_used": True,
        "data_quality": "fallback",
    }
    macro = build_macro_events(fallback_wits, {"shock_score": 0.2, "ts": "2026-08-18T00:00:00+00:00"})
    assert macro["degraded"] is True
    assert all(event.get("source") != "WITS" for event in macro["events"])
    assert any((event.get("details") or {}).get("demo") for event in macro["events"])

    geo = compute_geopolitical_index({"wits": fallback_wits, "gdelt": {"shock_score": 0.2}})
    assert geo["provider_status"]["wits"] == "degraded"
    assert geo["data_quality"] == "degraded"
    assert geo["tariff_score"] != 99.0


def test_stablecoin_routes_keep_missing_prices_unavailable(monkeypatch):
    import backend.api.stablecoin_routes as routes

    store = FakeStateStore()
    monkeypatch.setattr(routes, "_store", store)
    latest = routes.get_latest()
    assert set(latest) == {"USDC", "USDT", "DAI"}
    for symbol, row in latest.items():
        assert row["available"] is False
        assert row["price"] is None
        assert row["status"] == "unavailable"
        assert row["quality"]["observed"] is False

    health = routes.get_health()
    for row in health["health"].values():
        assert row["stress"] is None
        assert row["peg_break_probability"] is None
    assert health["alerts"] == []


def test_stablecoin_routes_use_canonical_observed_snapshot_without_inventing_others(monkeypatch):
    import backend.api.stablecoin_routes as routes

    store = FakeStateStore({
        "price:pyth:USDC_USD": {
            "price": 0.999,
            "ts": "2026-08-18T20:00:00+00:00",
        }
    })
    monkeypatch.setattr(routes, "_store", store)
    latest = routes.get_latest()
    assert latest["USDC"]["available"] is True
    assert latest["USDC"]["source"] == "pyth"
    assert latest["USDC"]["price"] == 0.999
    assert latest["USDC"]["quality"]["observed"] is True
    assert latest["USDT"]["available"] is False
    assert latest["DAI"]["available"] is False
