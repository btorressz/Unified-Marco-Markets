"""Credential-optional, bounded WTO Timeseries API ingestion."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import hashlib
import json

import httpx

from backend import config
from backend.core.state_keys import WTO_TRADE
from backend.core.state_store import StateStore
from backend.data.repositories.ingest_repo import IngestRepository
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.compute.geopolitical_evidence import normalize_research_event
from backend.ingest.quality import authoritative_evidence_envelope, observation_quality

WTO_SOURCE_ID = "wto_trade"
WTO_URL = "https://api.wto.org/timeseries/v1/indicator"
MAX_INDICATORS, MAX_REPORTERS, MAX_PARTNERS, MAX_RECORDS = 5, 10, 10, 500


def bounded(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))[:limit]


def normalize_wto_record(row: dict[str, Any], *, retrieved_at: str) -> dict[str, Any] | None:
    indicator = row.get("IndicatorCode") or row.get("indicator_code")
    reporter_code = row.get("ReportingEconomyCode") or row.get("reporter_code")
    period = row.get("Year") or row.get("Period") or row.get("period")
    if indicator is None or reporter_code is None or period is None or row.get("Value", row.get("value")) is None:
        return None
    observation = {
        "indicator_code": str(indicator), "indicator_name": row.get("Indicator") or row.get("indicator_name"),
        "reporter": row.get("ReportingEconomy") or row.get("reporter"), "reporter_code": str(reporter_code),
        "partner": row.get("PartnerEconomy") or row.get("partner"), "partner_code": row.get("PartnerEconomyCode") or row.get("partner_code"),
        "product": row.get("ProductOrSector") or row.get("product"), "product_code": row.get("ProductOrSectorCode") or row.get("product_code"),
        "period": str(period), "frequency": row.get("FrequencyCode") or row.get("frequency"),
        "value": row.get("Value", row.get("value")), "unit": row.get("Unit") or row.get("unit"),
    }
    identity = "|".join(str(observation[k] or "") for k in ("indicator_code", "reporter_code", "partner_code", "product_code", "period", "frequency"))
    return authoritative_evidence_envelope(
        source="WTO", source_id=WTO_SOURCE_ID, authority="World Trade Organization", jurisdiction="International",
        dataset="WTO Timeseries", source_record_id=identity, source_record_type="trade_indicator",
        provider_updated_at=row.get("UpdatedDate") or row.get("provider_updated_at"), retrieved_at=retrieved_at,
        observation=observation, transformation="wto_timeseries_normalization", transformation_version=1,
    )


class WTOIngestor:
    def __init__(self, state_store=None, ingest_repo=None, client_factory=None, api_key: str | None = None,
                 indicators=None, reporters=None, partners=None, research_event_repo=None):
        self.state_store = state_store or StateStore(); self.ingest_repo = ingest_repo or IngestRepository()
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=30.0))
        self.api_key = config.WTO_API_KEY if api_key is None else api_key
        self.indicators = bounded(indicators or config.WTO_INDICATORS, MAX_INDICATORS)
        self.reporters = bounded(reporters or config.WTO_REPORTERS, MAX_REPORTERS)
        self.partners = bounded(partners or config.WTO_PARTNERS, MAX_PARTNERS)
        self.research_event_repo = research_event_repo or ResearchEventRepository()

    def unavailable(self, status: str) -> dict[str, Any]:
        return {"source": "WTO", "source_id": WTO_SOURCE_ID, "provider_status": status,
                "quality": observation_quality(source="WTO", source_id=WTO_SOURCE_ID, available=False, authoritative=True, contract_version=2),
                "observation_count": 0, "latest_observations": []}

    async def fetch(self, run_context=None) -> dict[str, Any]:
        if not self.api_key:
            if run_context: run_context.metadata["provider_status"] = "not_configured"; run_context.mark_success()
            return self.unavailable("not_configured")
        retrieved_at = datetime.now(timezone.utc).isoformat()
        params = {"i": ",".join(self.indicators), "r": ",".join(self.reporters), "fmt": "json", "max": MAX_RECORDS}
        if self.partners: params["p"] = ",".join(self.partners)
        try:
            async with self.client_factory() as client:
                response = await client.get(WTO_URL, params=params, headers={"Ocp-Apim-Subscription-Key": self.api_key})
                response.raise_for_status(); payload = response.json()
        except Exception as exc:
            if run_context: run_context.mark_failure(exc)
            return self.unavailable("unavailable")
        raw = payload.get("Dataset", payload.get("data", [])) if isinstance(payload, dict) else []
        records = [record for row in raw[:MAX_RECORDS] if isinstance(row, dict) and (record := normalize_wto_record(row, retrieved_at=retrieved_at))]
        provenance_ids = []
        if run_context: run_context.record_received(len(records)); run_context.mark_success()
        for record in records:
            saved = self.ingest_repo.record_source_observation(
                ingest_run_id=getattr(run_context, "run_id", None), source_id=WTO_SOURCE_ID,
                artifact_type="wto_trade_observation", artifact_key=record["evidence"]["source_record_id"],
                observation=record, quality=record["quality"], provider_timestamp=record["evidence"]["provider_updated_at"], received_at=retrieved_at,
                lineage={"provider": "WTO Timeseries API", "artifact": "indicator observation", "transformation": "WTO normalizer v1"},
            )
            if saved and saved.get("id") is not None: provenance_ids.append(str(saved["id"]))
            evidence=record["evidence"]; observation=record["observation"]
            digest=hashlib.sha256(json.dumps(observation,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
            authority=record.get("authority") or {}
            event=normalize_research_event(event_family="trade_observation",event_type="WTO_TRADE_OBSERVATION",
                source="WTO",source_id=WTO_SOURCE_ID,source_record_id=evidence["source_record_id"],claim_type="observed_evidence",
                event_timestamp=evidence.get("retrieved_at"),event_time_basis="ingest_observed_at",
                transition={"content_hash":digest,"provider_updated_at":evidence.get("provider_updated_at")},
                observed=True,authoritative=True,study_eligible=False,authority=authority.get("name"),jurisdiction=authority.get("jurisdiction"),
                provider_updated_at=evidence.get("provider_updated_at"),retrieved_at=evidence.get("retrieved_at"),
                source_record_type=evidence.get("source_record_type"),evidence_contract_version=2,
                transformation=evidence.get("transformation"),transformation_version=str(evidence.get("transformation_version") or ""),
                content_hash=digest,payload=observation,evidence=evidence,
                lineage={"ingest_run_id":str(getattr(run_context,"run_id","") or ""),"provenance_id":str(saved.get("id")) if saved else None})
            self.research_event_repo.insert_event_idempotent(event)
        if run_context: run_context.record_persisted(len(records))
        snapshot = {"source": "WTO", "source_id": WTO_SOURCE_ID, "provider_status": "ok",
                    "quality": observation_quality(source="WTO", source_id=WTO_SOURCE_ID, available=True, authoritative=True, contract_version=2),
                    "retrieved_at": retrieved_at, "indicators_requested": self.indicators, "reporters_requested": self.reporters,
                    "observation_count": len(records), "latest_observations": records[-50:], "provenance_ids": provenance_ids[-50:]}
        self.state_store.set_snapshot(WTO_TRADE, snapshot, ttl=172800)
        return snapshot
