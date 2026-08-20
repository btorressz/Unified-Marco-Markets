from backend.compute.geopolitical_evidence import deterministic_event_key, normalize_research_event
import backend.data.repositories.research_event_repo as module


def event(change="ADDED", current="b"):
    return normalize_research_event(event_family="sanctions", event_type=f"OFAC_SANCTION_{change}",
        source="OFAC", source_id="ofac_sanctions", source_record_id="123", claim_type="observed_evidence",
        event_timestamp="2026-08-20T10:00:00+00:00", event_time_basis="provider_change_detected_at_retrieval",
        transition={"change_type":change,"previous_record_hash":"a","current_record_hash":current},
        observed=True, authoritative=True, study_eligible=True, payload={"name":"Example"}, evidence={}, lineage={})


def test_event_key_is_deterministic_and_transition_sensitive():
    assert event()["event_key"] == event()["event_key"]
    assert event()["event_key"] != event("UPDATED", "c")["event_key"]
    assert deterministic_event_key(source_id="s",source_record_id="1",event_type="X") == deterministic_event_key(source_id="s",source_record_id="1",event_type="X")


def test_normalized_time_meanings_remain_distinct_and_no_effective_time_is_invented():
    row=event()
    assert row["event_timestamp"] == "2026-08-20T10:00:00+00:00"
    assert row["event_time_basis"] == "provider_change_detected_at_retrieval"
    assert row.get("effective_at") is None
    assert row["execution_eligible"] is False


def test_repository_insert_is_idempotent_and_old_row_is_immutable(monkeypatch):
    rows={}
    def insert(sql, params):
        key=params[0]
        if key in rows: return None
        rows[key]={"event_key":key,"payload":{"name":"Example"}}
        return rows[key]
    monkeypatch.setattr(module,"execute_returning",insert)
    monkeypatch.setattr(module,"execute_query",lambda sql,params: [rows[params[0]]] if params[0] in rows else [])
    repo=module.ResearchEventRepository(); original=event()
    assert repo.insert_event_idempotent(original) == repo.insert_event_idempotent({**original,"payload":{"name":"Mutated"}})
    assert len(rows)==1 and next(iter(rows.values()))["payload"]["name"] == "Example"
    repo.insert_event_idempotent(event("UPDATED","c"))
    assert len(rows)==2


def test_listing_is_hard_bounded_and_parameterized(monkeypatch):
    captured={}
    def query(sql,params): captured.update(sql=sql,params=params); return []
    monkeypatch.setattr(module,"execute_query",query)
    module.ResearchEventRepository().list_events(limit=9999,event_family="sanctions",source_id="ofac_sanctions",study_eligible=True)
    assert captured["params"][-1] == module.MAX_LIST_LIMIT
    assert "event_family = %s" in captured["sql"] and "study_eligible = %s" in captured["sql"]


def test_repository_exposes_no_mutation_or_delete_path():
    names=set(dir(module.ResearchEventRepository))
    assert not ({"update_event","delete_event","save_event"} & names)
