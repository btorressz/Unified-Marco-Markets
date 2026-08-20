import logging
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from backend.config import WITS_COUNTRIES, WITS_PRODUCTS
from backend.core.event_bus import EventBus, EventType
from backend.core.state_keys import WITS_AGGREGATE, WITS_LATEST_LEGACY
from backend.core.state_store import StateStore
from backend.data.repositories.ingest_repo import IngestRepository
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.compute.geopolitical_evidence import normalize_research_event
from backend.ingest.quality import observation_quality

logger = logging.getLogger(__name__)

WITS_BASE_URL = "https://wits.worldbank.org/API/V1/SDMX/V21/rest/data"
# Keep the literal for the long-standing state-contract regression check while
# still asserting the centralized key has not drifted.
WITS_AGGREGATE_SNAPSHOT_KEY = "wits:tariff:aggregate"
assert WITS_AGGREGATE_SNAPSHOT_KEY == WITS_AGGREGATE

WITS_SOURCE_ID = "wits_tariffs"
WITS_TRANSFORMATION = "wits_sdmx_observation_normalization"
WITS_TRANSFORMATION_VERSION = 1

# Existing configuration is intentionally human-readable. Resolve only the
# aliases the repository ships by default; unknown configured values pass
# through unchanged so operators can use provider-native identifiers.
WITS_PARTNER_ALIASES = {
    "USA": "840",
    "CHN": "156",
    "EU": "EUN",
    "EUN": "EUN",
}
WITS_PRODUCT_ALIASES = {
    "TOTAL": "Total",
    "CAPITAL": "UNCTAD-SoP4",
    "CONSUMER": "UNCTAD-SoP3",
    "INTERMEDIATE": "UNCTAD-SoP2",
    "RAW": "UNCTAD-SoP1",
}


def _empty_result(*, reason: str, requested: dict[str, str], provider_query: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame(columns=[
        "reporter", "partner", "product", "year", "indicator", "tariff_rate",
        "observation_key", "dimensions",
    ])
    df.attrs.update({
        "observed": False,
        "available": False,
        "reason": reason,
        "requested": requested,
        "provider_query": provider_query,
    })
    return df


def _dimension_value(dimension: dict[str, Any], index: int) -> dict[str, Any] | None:
    values = dimension.get("values") or []
    if index < 0 or index >= len(values):
        return None
    value = values[index]
    return value if isinstance(value, dict) else {"id": value}


def _normalize_dimension_id(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


class WITSIngestor:

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_store: StateStore | None = None,
        ingest_repo: IngestRepository | None = None,
        research_event_repo: ResearchEventRepository | None = None,
    ):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
        self.ingest_repo = ingest_repo or IngestRepository()
        self.research_event_repo = research_event_repo or ResearchEventRepository()

    @staticmethod
    def _provider_dimensions(reporter: str, partner: str, product: str) -> dict[str, str]:
        return {
            "reporter": WITS_PARTNER_ALIASES.get(str(reporter).upper(), str(reporter)),
            "partner": WITS_PARTNER_ALIASES.get(str(partner).upper(), str(partner)),
            "product": WITS_PRODUCT_ALIASES.get(str(product).upper(), str(product)),
        }

    async def fetch_tariff_data(
        self,
        reporter: str = "840",
        partner: str = "156",
        product: str = "TOTAL",
        run_context=None,
    ) -> pd.DataFrame:
        requested = {"reporter": str(reporter), "partner": str(partner), "product": str(product)}
        provider_query = self._provider_dimensions(reporter, partner, product)
        url = (
            f"{WITS_BASE_URL}/DF_WITS_Tariff/"
            f"{provider_query['reporter']}.{provider_query['partner']}.{provider_query['product']}"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
                resp.raise_for_status()
                data = resp.json()
            records = self._parse_response(
                data,
                reporter=provider_query["reporter"],
                partner=provider_query["partner"],
                product=provider_query["product"],
            )
            if not records:
                logger.warning(
                    "WITS returned empty data for %s->%s [%s]",
                    provider_query["reporter"], provider_query["partner"], provider_query["product"],
                )
                if run_context:
                    run_context.metadata.setdefault("batch_failures", []).append({
                        **requested,
                        "reason": "provider_empty_response",
                    })
                return _empty_result(
                    reason="provider_empty_response",
                    requested=requested,
                    provider_query=provider_query,
                )

            df = pd.DataFrame(records)
            df.attrs.update({
                "observed": True,
                "available": True,
                "requested": requested,
                "provider_query": provider_query,
            })
            if run_context:
                run_context.record_received(len(df))
            persisted = self._store_and_emit(
                df,
                requested=requested,
                provider_query=provider_query,
                run_context=run_context,
            )
            if run_context and persisted:
                run_context.record_persisted(persisted)
            return df
        except Exception as exc:
            logger.warning(
                "WITS API failed for %s->%s [%s]; no synthetic tariff observation will be emitted",
                provider_query["reporter"], provider_query["partner"], provider_query["product"],
                exc_info=True,
            )
            if run_context:
                run_context.metadata.setdefault("batch_failures", []).append({
                    **requested,
                    "reason": "provider_request_failure",
                    "error_type": type(exc).__name__,
                })
            return _empty_result(
                reason="provider_request_failure",
                requested=requested,
                provider_query=provider_query,
            )

    def _parse_response(
        self,
        data: dict,
        *,
        reporter: str,
        partner: str,
        product: str,
    ) -> list[dict]:
        """Normalize SDMX observations without assuming a fixed dimension order."""
        records: list[dict] = []
        try:
            observations = data.get("dataSets", [{}])[0].get("observations", {}) or {}
            structure = data.get("structure") or {}
            dimension_specs = ((structure.get("dimensions") or {}).get("observation") or [])

            for key, values in observations.items():
                if not values or values[0] is None:
                    continue
                try:
                    tariff_rate = float(values[0])
                except (TypeError, ValueError):
                    continue

                indices = [int(part) for part in str(key).split(":") if str(part) != ""]
                dimensions: dict[str, Any] = {}
                for position, dimension in enumerate(dimension_specs):
                    if position >= len(indices) or not isinstance(dimension, dict):
                        continue
                    selected = _dimension_value(dimension, indices[position])
                    if selected is None:
                        continue
                    dim_id = str(dimension.get("id") or f"dimension_{position}")
                    dimensions[dim_id] = {
                        "id": selected.get("id"),
                        "name": selected.get("name"),
                    }

                def pick(*names: str) -> Any:
                    wanted = {_normalize_dimension_id(name) for name in names}
                    for dim_id, selected in dimensions.items():
                        if _normalize_dimension_id(dim_id) in wanted:
                            return selected.get("id") or selected.get("name")
                    return None

                year_raw = pick("TIME_PERIOD", "TIME", "YEAR")
                year = None
                if year_raw is not None and str(year_raw).isdigit() and len(str(year_raw)) == 4:
                    year = int(year_raw)

                records.append({
                    "reporter": pick("REPORTER", "REPORTER_ID", "REF_AREA") or reporter,
                    "partner": pick("PARTNER", "PARTNER_ID", "COUNTERPART_AREA") or partner,
                    "product": pick("PRODUCT", "PRODUCT_ID", "COMMODITY") or product,
                    "year": year,
                    "indicator": pick("INDICATOR", "INDICATOR_ID", "MEASURE"),
                    "tariff_rate": tariff_rate,
                    "observation_key": str(key),
                    "dimensions": dimensions,
                })
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning("Failed to parse WITS SDMX response", exc_info=True)
        return records

    def _record_observations(self, df: pd.DataFrame, *, run_context, provider_query: dict[str, str]) -> int:
        if not run_context or not getattr(run_context, "run_id", None):
            return 0
        persisted = 0
        received_at = getattr(run_context, "received_at", None)
        for row in df.to_dict(orient="records"):
            key_parts = [
                str(row.get("reporter") or provider_query["reporter"]),
                str(row.get("partner") or provider_query["partner"]),
                str(row.get("product") or provider_query["product"]),
                str(row.get("year") or "unknown"),
                str(row.get("indicator") or "unknown"),
                str(row.get("observation_key") or "unknown"),
            ]
            quality = observation_quality(
                source="WITS",
                source_id=WITS_SOURCE_ID,
                available=True,
                authoritative=True,
                execution_eligible=False,
                synthetic=False,
                degraded=False,
                as_of=None,
                transformation=WITS_TRANSFORMATION,
                transformation_version=WITS_TRANSFORMATION_VERSION,
            )
            try:
                saved = self.ingest_repo.record_source_observation(
                    ingest_run_id=run_context.run_id,
                    source_id=WITS_SOURCE_ID,
                    artifact_type="tariff_observation",
                    artifact_key="|".join(key_parts),
                    observation=row,
                    quality=quality,
                    lineage={
                        "transformation": WITS_TRANSFORMATION,
                        "transformation_version": WITS_TRANSFORMATION_VERSION,
                        "provider_query": provider_query,
                    },
                    provider_timestamp=getattr(run_context, "provider_timestamp", None),
                    received_at=received_at,
                )
                persisted += int(bool(saved))
                digest=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
                observed_at=received_at or datetime.now(timezone.utc).isoformat()
                event=normalize_research_event(event_family="tariff_observation",event_type="WITS_TARIFF_OBSERVATION",
                    source="WITS",source_id=WITS_SOURCE_ID,source_record_id="|".join(key_parts),claim_type="observed_evidence",
                    event_timestamp=observed_at,event_time_basis="ingest_observed_at",transition={"content_hash":digest},
                    observed=True,authoritative=True,study_eligible=False,retrieved_at=observed_at,
                    transformation=WITS_TRANSFORMATION,transformation_version=str(WITS_TRANSFORMATION_VERSION),content_hash=digest,
                    payload=row,evidence={"observation_period":row.get("year")},lineage={"ingest_run_id":str(run_context.run_id),"provenance_id":str(saved.get("id")) if saved else None,"provider_query":provider_query})
                self.research_event_repo.insert_event_idempotent(event)
            except Exception:
                logger.warning("Failed to persist WITS tariff observation provenance", exc_info=True)
        return persisted

    def _store_and_emit(
        self,
        df: pd.DataFrame,
        *,
        requested: dict[str, str],
        provider_query: dict[str, str],
        run_context=None,
    ) -> int:
        now = datetime.now(timezone.utc)
        snapshot_key = (
            f"wits:tariff:{provider_query['reporter']}:"
            f"{provider_query['partner']}:{provider_query['product']}"
        )
        quality = observation_quality(
            source="WITS",
            source_id=WITS_SOURCE_ID,
            available=True,
            authoritative=True,
            execution_eligible=False,
            synthetic=False,
            degraded=False,
            as_of=None,
            transformation=WITS_TRANSFORMATION,
            transformation_version=WITS_TRANSFORMATION_VERSION,
        )
        self.state_store.set_snapshot(snapshot_key, {
            "reporter": provider_query["reporter"],
            "partner": provider_query["partner"],
            "product": provider_query["product"],
            "requested": requested,
            "records": df.to_dict(orient="records"),
            "available": True,
            "synthetic": False,
            "fallback_used": False,
            "quality": quality,
            "ts": now.isoformat(),
        }, ttl=86400)

        self.event_bus.emit(
            EventType.INDEX_UPDATE,
            source="wits_ingest",
            payload={
                "reporter": provider_query["reporter"],
                "partner": provider_query["partner"],
                "product": provider_query["product"],
                "row_count": len(df),
                "available": True,
                "synthetic": False,
            },
        )
        return self._record_observations(df, run_context=run_context, provider_query=provider_query)

    def _store_aggregate_freshness(self, results: list[pd.DataFrame], run_context=None) -> dict | None:
        """Publish an aggregate only from actual provider observations."""
        observed = [
            df for df in results
            if isinstance(df, pd.DataFrame) and not df.empty and df.attrs.get("observed") is True
        ]
        if not observed:
            logger.warning("No observed WITS batches available; preserving the last observed aggregate")
            return None

        rates: list[float] = []
        for df in observed:
            if "tariff_rate" in df.columns:
                numeric = pd.to_numeric(df["tariff_rate"], errors="coerce").dropna()
                rates.extend(float(value) for value in numeric.tolist())
        if not rates:
            logger.warning("Observed WITS batches contained no numeric tariff rates; aggregate not updated")
            return None

        now = datetime.now(timezone.utc)
        expected_batches = len(WITS_COUNTRIES) * len(WITS_PRODUCTS)
        failed_batches = max(0, expected_batches - len(observed))
        tariff_pressure = round(sum(rates) / len(rates), 4)
        quality = observation_quality(
            source="WITS",
            source_id=WITS_SOURCE_ID,
            available=True,
            authoritative=True,
            execution_eligible=False,
            synthetic=False,
            degraded=failed_batches > 0,
            as_of=None,
            transformation="wits_observed_tariff_mean",
            transformation_version=1,
        )
        payload = {
            "reporter": "840",
            "countries": list(WITS_COUNTRIES),
            "products": list(WITS_PRODUCTS),
            "batch_count": len(results),
            "successful_batches": len(observed),
            "failed_batches": failed_batches,
            "records_returned": sum(len(df) for df in observed),
            "tariff_pressure": tariff_pressure,
            "value": tariff_pressure,
            "available": True,
            "synthetic": False,
            "fallback_used": False,
            "data_quality": "partial_provider" if failed_batches else "provider",
            "quality": quality,
            "ts": now.isoformat(),
        }
        self.state_store.set_snapshot(WITS_AGGREGATE, payload, ttl=86400)
        self.state_store.set_snapshot(WITS_LATEST_LEGACY, payload, ttl=86400)
        if run_context and getattr(run_context, "run_id", None):
            try:
                self.ingest_repo.record_provenance(
                    run_context.run_id,
                    WITS_SOURCE_ID,
                    "tariff_aggregate",
                    artifact_key=WITS_AGGREGATE,
                    received_at=getattr(run_context, "received_at", None),
                    fallback_used=False,
                    quality=quality,
                    lineage={
                        "transformation": "wits_observed_tariff_mean",
                        "transformation_version": 1,
                        "source_artifact_type": "tariff_observation",
                        "observed_batches": len(observed),
                    },
                    metadata={
                        "tariff_pressure": tariff_pressure,
                        "records_returned": payload["records_returned"],
                    },
                )
            except Exception:
                logger.warning("Failed to persist WITS aggregate provenance", exc_info=True)
        return payload

    async def fetch_all(self, run_context=None) -> list[pd.DataFrame]:
        results: list[pd.DataFrame] = []
        for country in WITS_COUNTRIES:
            for product in WITS_PRODUCTS:
                df = await self.fetch_tariff_data(
                    reporter="840",
                    partner=country,
                    product=product,
                    run_context=run_context,
                )
                results.append(df)

        observed_count = sum(
            1 for df in results
            if isinstance(df, pd.DataFrame) and not df.empty and df.attrs.get("observed") is True
        )
        if run_context:
            run_context.metadata["expected_batches"] = len(results)
            run_context.metadata["observed_batches"] = observed_count
            if observed_count == len(results) and observed_count > 0:
                run_context.mark_success()
            elif observed_count > 0:
                run_context.provider_success = True
                run_context.metadata["partial_provider_failure"] = True
            else:
                run_context.mark_failure(RuntimeError("wits_no_observed_batches"))

        try:
            self._store_aggregate_freshness(results, run_context=run_context)
        except Exception:
            logger.warning("Failed to publish WITS aggregate freshness snapshot", exc_info=True)
        return results
