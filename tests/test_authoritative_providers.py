import asyncio
from copy import deepcopy

from backend.compute.sanctions_risk import score_sanctions
from backend.ingest.ofac_ingest import OFACIngestor, dataset_hash
from backend.ingest.provenance import IngestRunContext
from backend.ingest.wto_ingest import MAX_INDICATORS, MAX_REPORTERS, WTOIngestor, normalize_wto_record


class Store:
    def __init__(self): self.snapshots = {}; self.writes = []
    def set_snapshot(self, key, value, ttl=None): self.snapshots[key] = value; self.writes.append((key, value)); return True
    def get_snapshot(self, key): return self.snapshots.get(key)


class Repo:
    def __init__(self): self.rows = []
    def record_source_observation(self, **kwargs): self.rows.append(kwargs); return {"id": len(self.rows)}


class Response:
    def __init__(self, *, content=b"", payload=None, failure=False): self.content = content; self.payload = payload; self.failure = failure
    def raise_for_status(self):
        if self.failure: raise RuntimeError("provider down")
    def json(self): return self.payload


class Client:
    def __init__(self, response): self.response = response
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def get(self, *args, **kwargs): return self.response


XML = b'''<sdnList><sdnEntry><uid>123</uid><firstName>Jane</firstName><lastName>Example</lastName><sdnType>Individual</sdnType><programList><program>TEST</program></programList><akaList><aka><firstName>J</firstName><lastName>Example</lastName></aka></akaList><nationalityList><nationality><country>Exampleland</country></nationality></nationalityList></sdnEntry></sdnList>'''


def records(at="2026-08-19T00:00:00+00:00"):
    return OFACIngestor.parse_xml(XML, retrieved_at=at)


def test_ofac_normalization_identity_hash_and_deltas_are_deterministic():
    first_records = records()
    assert first_records[0]["quality"]["authoritative"] is True
    assert first_records[0]["observation"]["source_record_id"] == "123"
    assert first_records[0]["observation"]["aliases"] == ["J Example"]
    assert dataset_hash(first_records) == dataset_hash(records("2026-08-20T00:00:00+00:00"))

    ingestor = OFACIngestor(state_store=Store(), ingest_repo=Repo())
    first = ingestor.process_records(first_records, retrieved_at="2026-08-19T00:00:00+00:00")
    assert first["baseline_initialized"] is True and first["changes_available"] is False
    assert first["added_count"] == 0
    assert score_sanctions(ofac=first)["new_sanctions"] is False

    same = ingestor.process_records(records("later"), retrieved_at="later")
    assert (same["added_count"], same["updated_count"], same["removed_count"]) == (0, 0, 0)
    assert same["unchanged_count"] == 1

    added_records = records() + deepcopy(records())
    added_records[1]["observation"]["source_record_id"] = "456"
    added_records[1]["observation"]["provider_ids"]["uid"] = "456"
    added = ingestor.process_records(added_records, retrieved_at="later")
    assert added["added_count"] == 1

    added_records[0]["observation"]["remarks"] = "changed"
    updated = ingestor.process_records(added_records, retrieved_at="later")
    assert updated["updated_count"] == 1

    removed = ingestor.process_records(added_records[:1], retrieved_at="later")
    assert removed["removed_count"] == 1


def test_malformed_ofac_object_is_not_authority():
    result = score_sanctions(ofac={"added_count": 99})
    assert result["authoritative_evidence"] is False
    assert result["new_sanctions"] is False
    assert result["entity_additions"] == 0


def test_ofac_failure_preserves_last_good_snapshot():
    store = Store(); store.snapshots["sanctions:ofac:latest"] = {"known_good": True}
    ingestor = OFACIngestor(state_store=store, ingest_repo=Repo(), client_factory=lambda: Client(Response(failure=True)))
    result = asyncio.run(ingestor.fetch(IngestRunContext("ofac_sanctions")))
    assert result["provider_status"] == "unavailable" and result["quality"]["observed"] is False
    assert store.snapshots["sanctions:ofac:latest"] == {"known_good": True}
    assert store.writes == []


def test_wto_missing_key_is_truthful_and_does_not_write():
    store, repo = Store(), Repo()
    context = IngestRunContext("wto_trade")
    result = asyncio.run(WTOIngestor(state_store=store, ingest_repo=repo, api_key="").fetch(context))
    assert result["provider_status"] == "not_configured"
    assert result["quality"]["observed"] is False
    assert result["latest_observations"] == []
    assert store.writes == [] and repo.rows == []


def test_wto_normalization_preserves_dimensions_and_nulls():
    row = normalize_wto_record({
        "IndicatorCode": "ITS_MTV_AX", "Indicator": "Trade value", "ReportingEconomyCode": "840",
        "ReportingEconomy": "United States", "PartnerEconomyCode": "156", "PartnerEconomy": "China",
        "ProductOrSectorCode": "AG", "ProductOrSector": "Agriculture", "Year": 2025,
        "FrequencyCode": "A", "Value": 12.5, "Unit": "US$ million",
    }, retrieved_at="now")
    assert row["quality"]["observed"] is True and row["quality"]["execution_eligible"] is False
    assert row["observation"]["partner_code"] == "156" and row["observation"]["unit"] == "US$ million"
    minimal = normalize_wto_record({"IndicatorCode": "I", "ReportingEconomyCode": "R", "Year": 2025, "Value": 1}, retrieved_at="now")
    assert minimal["observation"]["partner"] is None and minimal["observation"]["product_code"] is None


def test_wto_configuration_is_bounded_and_fixture_provenance_is_reused():
    store, repo = Store(), Repo()
    ingestor = WTOIngestor(state_store=store, ingest_repo=repo, api_key="key",
                          indicators=[str(i) for i in range(20)], reporters=[str(i) for i in range(20)])
    assert len(ingestor.indicators) == MAX_INDICATORS
    assert len(ingestor.reporters) == MAX_REPORTERS
    ingestor.client_factory = lambda: Client(Response(payload={"Dataset": [{
        "IndicatorCode": "I", "ReportingEconomyCode": "R", "Year": 2025, "Value": 2, "Unit": "%",
    }]}))
    result = asyncio.run(ingestor.fetch(IngestRunContext("wto_trade", run_id="run")))
    assert result["observation_count"] == 1 and len(result["latest_observations"]) == 1
    assert repo.rows[0]["source_id"] == "wto_trade"
    assert repo.rows[0]["lineage"]["transformation"] == "WTO normalizer v1"
