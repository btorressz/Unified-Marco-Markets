import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

from backend.config import WITS_COUNTRIES, WITS_PRODUCTS
from backend.core.event_bus import EventBus, EventType
from backend.core.state_keys import WITS_AGGREGATE
from backend.core.state_store import StateStore

logger = logging.getLogger(__name__)

WITS_BASE_URL = "https://wits.worldbank.org/API/V1/SDMX/V21/rest/data"
WITS_AGGREGATE_SNAPSHOT_KEY = WITS_AGGREGATE

_SAMPLE_TARIFF_DATA = [
    {"reporter": "USA", "partner": "CHN", "product": "TOTAL", "year": 2025, "tariff_rate": 19.3, "trade_value": 450000},
    {"reporter": "USA", "partner": "CHN", "product": "Capital", "year": 2025, "tariff_rate": 7.5, "trade_value": 120000},
    {"reporter": "CHN", "partner": "USA", "product": "TOTAL", "year": 2025, "tariff_rate": 21.1, "trade_value": 380000},
]


class WITSIngestor:

    def __init__(self, event_bus: EventBus | None = None, state_store: StateStore | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()

    async def fetch_tariff_data(
        self,
        reporter: str = "840",
        partner: str = "156",
        product: str = "TOTAL",
        run_context=None,
    ) -> pd.DataFrame:
        url = f"{WITS_BASE_URL}/DF_WITS_Tariff/{reporter}.{partner}.{product}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
                resp.raise_for_status()
                data = resp.json()
                records = self._parse_response(data)
                if not records:
                    logger.warning("WITS returned empty data for %s->%s [%s]", reporter, partner, product)
                    df = self._fallback_data()
                    if run_context:
                        run_context.record_received(len(df))
                        run_context.mark_fallback(fallback_type="sample", reason="provider_empty_response")
                    return df
                df = pd.DataFrame(records)
                if run_context:
                    run_context.mark_success()
                    run_context.record_received(len(df))
                self._store_and_emit(df, reporter, partner, product)
                if run_context:
                    run_context.record_persisted(len(df))
                return df
        except Exception as exc:
            logger.warning("WITS API failed for %s->%s [%s], using cached/sample data", reporter, partner, product, exc_info=True)
            df = self._fallback_data()
            if run_context:
                run_context.record_received(len(df))
                run_context.mark_failure(exc)
                run_context.mark_fallback(fallback_type="sample", reason="provider_request_failure")
            return df

    def _parse_response(self, data: dict) -> list[dict]:
        records = []
        try:
            observations = data.get("dataSets", [{}])[0].get("observations", {})
            for key, values in observations.items():
                records.append({
                    "key": key,
                    "tariff_rate": float(values[0]) if values else 0.0,
                })
        except (KeyError, IndexError, TypeError):
            logger.warning("Failed to parse WITS SDMX response", exc_info=True)
        return records

    def _fallback_data(self) -> pd.DataFrame:
        logger.info("Returning sample WITS tariff data")
        return pd.DataFrame(_SAMPLE_TARIFF_DATA)

    def _store_and_emit(self, df: pd.DataFrame, reporter: str, partner: str, product: str) -> None:
        snapshot_key = f"wits:tariff:{reporter}:{partner}:{product}"
        self.state_store.set_snapshot(snapshot_key, {
            "reporter": reporter,
            "partner": partner,
            "product": product,
            "records": df.to_dict(orient="records"),
            "ts": datetime.now(timezone.utc).isoformat(),
        }, ttl=86400)

        self.event_bus.emit(
            EventType.INDEX_UPDATE,
            source="wits_ingest",
            payload={
                "reporter": reporter,
                "partner": partner,
                "product": product,
                "row_count": len(df),
            },
        )

    def _store_aggregate_freshness(self, results: list[pd.DataFrame], run_context=None) -> None:
        """Publish one canonical WITS snapshot for freshness and downstream readers."""
        rates: list[float] = []
        for df in results:
            if isinstance(df, pd.DataFrame) and "tariff_rate" in df.columns:
                numeric = pd.to_numeric(df["tariff_rate"], errors="coerce").dropna()
                rates.extend(float(value) for value in numeric.tolist())
        tariff_pressure = round(sum(rates) / len(rates), 4) if rates else None
        fallback_used = bool(getattr(run_context, "fallback_used", False))
        self.state_store.set_snapshot(
            WITS_AGGREGATE,
            {
                "reporter": "840",
                "countries": list(WITS_COUNTRIES),
                "products": list(WITS_PRODUCTS),
                "batch_count": len(results),
                "records_returned": sum(len(df) for df in results),
                "tariff_pressure": tariff_pressure,
                "value": tariff_pressure,
                "fallback_used": fallback_used,
                "data_quality": "fallback" if fallback_used else "provider",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            ttl=86400,
        )

    async def fetch_all(self, run_context=None) -> list[pd.DataFrame]:
        results = []
        for country in WITS_COUNTRIES:
            for product in WITS_PRODUCTS:
                try:
                    df = await self.fetch_tariff_data(reporter="840", partner=country, product=product, run_context=run_context)
                    results.append(df)
                except Exception:
                    logger.warning("Failed to fetch WITS data for %s/%s", country, product, exc_info=True)
        try:
            self._store_aggregate_freshness(results, run_context=run_context)
        except Exception:
            logger.warning("Failed to publish WITS aggregate freshness snapshot", exc_info=True)
        return results
