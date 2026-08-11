from __future__ import annotations

from fastapi import APIRouter
from backend.core.state_keys import GDELT_LATEST, WITS_AGGREGATE
from backend.core.state_store import StateStore
from backend.compute.macro_events import build_macro_events, compute_impact, compute_event_reaction

router = APIRouter(prefix="/api/macro", tags=["macro"])
_store = StateStore()


def _events():
    wits = _store.get_snapshot(WITS_AGGREGATE)
    gdelt = _store.get_snapshot(GDELT_LATEST)
    return build_macro_events(wits, gdelt)


@router.get("/events")
def macro_events():
    return _events()


@router.get("/events/impact")
def macro_events_impact():
    events = _events().get("events", [])
    return compute_impact(events, _store.get_snapshot("desk:market:latest") or {})


@router.get("/events/{event_id}/reaction")
def macro_event_reaction(event_id: str):
    events = _events().get("events", [])
    event = next((e for e in events if e.get("id") == event_id), events[0] if events else {"id": event_id, "title": "fallback event", "score": 0, "severity": "low", "degraded": True})
    return compute_event_reaction(event, _store.get_snapshot("desk:market:latest") or {})
