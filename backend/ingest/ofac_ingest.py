"""Bounded runtime ingestion of OFAC's official machine-readable SDN XML."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx

from backend.core.state_keys import OFAC_SANCTIONS
from backend.core.state_store import StateStore
from backend.data.repositories.ingest_repo import IngestRepository
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.compute.geopolitical_evidence import normalize_research_event
from backend.ingest.quality import authoritative_evidence_envelope, observation_quality

OFAC_SOURCE_ID = "ofac_sanctions"
OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
MAX_RECENT_CHANGES = 100


def _text(node, name: str) -> str | None:
    found = node.find(f".//{{*}}{name}")
    return found.text.strip() if found is not None and found.text else None


def _texts(node, name: str) -> list[str]:
    return sorted({n.text.strip() for n in node.findall(f".//{{*}}{name}") if n.text and n.text.strip()})


def normalize_ofac_record(node, *, dataset: str = "SDN", retrieved_at: str | None = None) -> dict[str, Any] | None:
    uid = _text(node, "uid")
    if not uid:
        return None
    first, last = _text(node, "firstName"), _text(node, "lastName")
    name = " ".join(part for part in (first, last) if part) or _text(node, "name")
    aliases = []
    for alias in node.findall(".//{*}aka"):
        value = " ".join(filter(None, (_text(alias, "firstName"), _text(alias, "lastName"))))
        if value:
            aliases.append(value)
    addresses = []
    for address in node.findall(".//{*}address"):
        item = {key: _text(address, key) for key in ("address1", "address2", "city", "stateOrProvince", "postalCode", "country")}
        if any(item.values()):
            addresses.append(item)
    observation = {
        "source_record_id": uid, "provider_ids": {"uid": uid}, "list": dataset,
        "entity_name": name, "entity_type": _text(node, "sdnType"),
        "aliases": sorted(set(aliases)), "programs": _texts(node, "program"),
        "nationalities": sorted({_text(item, "country") for item in node.findall(".//{*}nationality") if _text(item, "country")}),
        "citizenships": sorted({_text(item, "country") for item in node.findall(".//{*}citizenship") if _text(item, "country")}),
        "addresses": addresses, "remarks": _text(node, "remarks"),
    }
    return authoritative_evidence_envelope(
        source="OFAC", source_id=OFAC_SOURCE_ID,
        authority="U.S. Department of the Treasury / OFAC", jurisdiction="US", dataset=dataset,
        source_record_id=uid, source_record_type=observation["entity_type"], observation=observation,
        retrieved_at=retrieved_at, transformation="ofac_sls_xml_normalization", transformation_version=1,
    )


def canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    return {"authority": record.get("authority"), "observation": record.get("observation")}


def record_hash(record: dict[str, Any]) -> str:
    raw = json.dumps(canonical_record(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def dataset_hash(records: list[dict[str, Any]]) -> str:
    rows = sorted((r["observation"]["source_record_id"], record_hash(r)) for r in records)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


class OFACIngestor:
    def __init__(self, state_store=None, ingest_repo=None, client_factory=None, research_event_repo=None):
        self.state_store = state_store or StateStore()
        self.ingest_repo = ingest_repo or IngestRepository()
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=60.0))
        self.research_event_repo = research_event_repo or ResearchEventRepository()
        self._baseline: dict[str, tuple[str, dict[str, Any]]] | None = None

    def _durable_baseline(self):
        if not hasattr(self.ingest_repo, "get_latest_completed_run"): return None
        run = self.ingest_repo.get_latest_completed_run(OFAC_SOURCE_ID)
        if not run: return None
        rows = self.ingest_repo.load_source_observations_for_run(
            OFAC_SOURCE_ID, run["id"], "ofac_sanctions_observation", limit=100000)
        baseline = {}
        for row in rows:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str): metadata = json.loads(metadata)
            record = metadata.get("observation")
            if record and (uid := (record.get("observation") or {}).get("source_record_id")):
                baseline[uid] = (record_hash(record), record)
        return baseline or None

    @staticmethod
    def parse_xml(content: bytes, *, retrieved_at: str) -> list[dict[str, Any]]:
        root = ElementTree.fromstring(content)
        return [row for node in root.findall(".//{*}sdnEntry") if (row := normalize_ofac_record(node, retrieved_at=retrieved_at))]

    async def fetch(self, run_context=None) -> dict[str, Any]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        try:
            async with self.client_factory() as client:
                response = await client.get(OFAC_SDN_URL)
                response.raise_for_status()
            records = self.parse_xml(response.content, retrieved_at=retrieved_at)
        except Exception as exc:
            if run_context:
                run_context.mark_failure(exc)
            return {"source": "OFAC", "source_id": OFAC_SOURCE_ID, "provider_status": "unavailable", "quality": observation_quality(source="OFAC", source_id=OFAC_SOURCE_ID, available=False, authoritative=True, contract_version=2), "observations": []}
        return self.process_records(records, retrieved_at=retrieved_at, run_context=run_context)

    def process_records(self, records: list[dict[str, Any]], *, retrieved_at: str, run_context=None) -> dict[str, Any]:
        if self._baseline is None:
            self._baseline = self._durable_baseline()
        current = {r["observation"]["source_record_id"]: (record_hash(r), r) for r in records}
        first = self._baseline is None
        changes: list[dict[str, Any]] = []
        counts = {"added_count": 0, "updated_count": 0, "removed_count": 0, "unchanged_count": 0}
        previous_dataset_hash = dataset_hash([row[1] for row in (self._baseline or {}).values()]) if not first else None
        current_dataset_hash = dataset_hash(records)
        if not first:
            previous = self._baseline or {}
            for uid, (digest, record) in current.items():
                change = "ADDED" if uid not in previous else "UPDATED" if previous[uid][0] != digest else "UNCHANGED"
                record["evidence"]["change_type"] = change
                counts[f"{change.lower()}_count"] += 1
                if change != "UNCHANGED":
                    changes.append({**record["observation"], "change_type": change, "change_detected_at": retrieved_at,
                                    "previous_record_hash": previous.get(uid, (None,))[0], "current_record_hash": digest})
            for uid, (_, record) in previous.items():
                if uid not in current:
                    counts["removed_count"] += 1
                    changes.append({**record["observation"], "change_type": "REMOVED", "change_detected_at": retrieved_at,
                                    "previous_record_hash": record_hash(record), "current_record_hash": None})
        self._baseline = current
        content_hash = current_dataset_hash
        provenance_ids = []
        if run_context:
            run_context.record_received(len(records)); run_context.mark_success()
        for record in records:
            record["evidence"]["content_hash"] = record_hash(record)
            saved = self.ingest_repo.record_source_observation(
                ingest_run_id=getattr(run_context, "run_id", None), source_id=OFAC_SOURCE_ID,
                artifact_type="ofac_sanctions_observation", artifact_key=f"SDN:{record['observation']['source_record_id']}",
                observation=record, quality=record["quality"], provider_timestamp=None, received_at=retrieved_at,
                lineage={"provider": "OFAC SLS", "artifact": "official SDN XML", "transformation": "OFAC normalizer v1"},
            )
            if saved and saved.get("id") is not None: provenance_ids.append(str(saved["id"]))
        for change in changes:
            transition = {"change_type": change["change_type"], "previous_record_hash": change.get("previous_record_hash"),
                          "current_record_hash": change.get("current_record_hash"), "previous_dataset_hash": previous_dataset_hash,
                          "current_dataset_hash": current_dataset_hash}
            event = normalize_research_event(
                event_family="sanctions", event_type=f"OFAC_SANCTION_{change['change_type']}", source="OFAC",
                source_id=OFAC_SOURCE_ID, source_record_id=change["source_record_id"], claim_type="observed_evidence",
                event_timestamp=retrieved_at, event_time_basis="provider_change_detected_at_retrieval", transition=transition,
                observed=True, authoritative=True, proxy=False, synthetic=False, study_eligible=True,
                authority="U.S. Department of the Treasury / OFAC", jurisdiction="US", detected_at=retrieved_at,
                retrieved_at=retrieved_at, effective_at=None, published_at=None, change_type=change["change_type"],
                source_record_type=change.get("entity_type"), evidence_contract_version=2,
                transformation="ofac_sls_xml_normalization", transformation_version="1", content_hash=change.get("current_record_hash"),
                dataset_version=current_dataset_hash, payload=change, evidence=transition,
                lineage={"ingest_run_id": str(getattr(run_context,"run_id","") or ""), "provenance_ids": provenance_ids})
            self.research_event_repo.insert_event_idempotent(event)
        if run_context: run_context.record_persisted(len(records))
        snapshot = {
            "source": "OFAC", "source_id": OFAC_SOURCE_ID, "provider_status": "ok",
            "quality": observation_quality(source="OFAC", source_id=OFAC_SOURCE_ID, available=True, authoritative=True, contract_version=2),
            "datasets": [{"dataset": "SDN", "content_hash": content_hash, "record_count": len(records)}],
            "retrieved_at": retrieved_at, "entity_count": len(records), **counts,
            "baseline_initialized": True, "changes_available": not first,
            "recent_changes": changes[:MAX_RECENT_CHANGES],
            "program_counts": dict(Counter(p for r in records for p in r["observation"]["programs"])),
            "provenance_ids": provenance_ids[:MAX_RECENT_CHANGES],
        }
        self.state_store.set_snapshot(OFAC_SANCTIONS, snapshot, ttl=172800)
        return snapshot
