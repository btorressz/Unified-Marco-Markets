from backend.ingest.gdelt_ingest import GDELT_EVENTS_SOURCE_ID, GDELTIngestor, normalize_gdelt_event


def sample():
    return {"GLOBALEVENTID": "123", "DATEADDED": "20260826143000", "SQLDATE": "20260826",
            "EventCode": "190", "EventBaseCode": "190", "EventRootCode": "19", "QuadClass": "4",
            "Actor1Name": "EXAMPLE", "Actor2Name": "OTHER", "SOURCEURL": "https://example.test/report"}


def test_gdelt_event_contract_is_observed_non_authoritative_and_study_eligible():
    event = normalize_gdelt_event(sample())
    assert event["source_id"] == GDELT_EVENTS_SOURCE_ID
    assert event["event_family"] == "conflict_diplomatic_political"
    assert event["observed"] is True and event["authoritative"] is False
    assert event["study_eligible"] is True and event["execution_eligible"] is False
    assert event["event_timestamp"] == "2026-08-26T14:30:00+00:00"
    assert event["event_time_basis"] == "provider_added_at"


def test_gdelt_events_are_idempotently_sent_to_durable_repository():
    class Repo:
        def __init__(self): self.keys = set()
        def insert_event_idempotent(self, event):
            fresh = event["event_key"] not in self.keys
            self.keys.add(event["event_key"])
            return event if fresh else None
    repo = Repo(); ingestor = GDELTIngestor(research_event_repo=repo)
    assert len(ingestor.process_events([sample(), sample()])) == 2
    assert len(repo.keys) == 1
