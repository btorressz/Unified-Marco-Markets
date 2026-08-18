import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

from backend.config import GDELT_KEYWORDS
from backend.core.event_bus import EventBus, EventType
from backend.core.state_store import StateStore
from backend.data.repositories.ingest_repo import IngestRepository
from backend.ingest.quality import observation_quality
from backend.compute.geopolitical_evidence import evidence_id, normalize_evidence_document

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
SHOCK_THRESHOLD = 5.0
GDELT_SOURCE_ID = "gdelt_macro_news"
MAX_EVIDENCE_DOCUMENTS = 20


class GDELTIngestor:

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_store: StateStore | None = None,
        ingest_repo: IngestRepository | None = None,
    ):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
        self.ingest_repo = ingest_repo or IngestRepository()
        self._last_shock_score: float = 0.0

    async def fetch_articles(
        self,
        keywords: list[str] | None = None,
        countries: list[str] | None = None,
        run_context=None,
    ) -> pd.DataFrame:
        keywords = keywords or GDELT_KEYWORDS
        query_str = " OR ".join(f'"{kw}"' for kw in keywords)
        if countries:
            country_filter = " OR ".join(f'sourcecountry:{c}' for c in countries)
            query_str = f"({query_str}) ({country_filter})"

        params = {
            "query": query_str,
            "mode": "ArtList",
            "maxrecords": "50",
            "format": "json",
            "sort": "DateDesc",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(GDELT_DOC_API, params=params)
                resp.raise_for_status()
                data = resp.json()
                articles = data.get("articles", [])
                if not articles:
                    logger.warning("GDELT returned no articles for query: %s", query_str[:80])
                    if run_context:
                        run_context.mark_success()
                        run_context.metadata["records_processed"] = 0
                    return pd.DataFrame()

                df = self._parse_articles(articles)
                if run_context:
                    run_context.mark_success()
                    run_context.record_received(len(df))
                    run_context.metadata["records_processed"] = len(df)
                shock_score = self._compute_shock_score(df)
                persisted = self._persist_evidence(df, run_context=run_context, query_str=query_str)
                self._store_results(df, shock_score)
                if run_context:
                    # The aggregate Redis snapshot is one persisted artifact;
                    # durable document evidence is counted separately when the
                    # provenance ledger is available.
                    run_context.record_persisted(1 + persisted)
                    run_context.metadata["evidence_documents_persisted"] = persisted
                self._check_shock_spike(shock_score)
                return df
        except Exception as exc:
            if run_context:
                run_context.mark_failure(exc)
            logger.warning("GDELT API failed, returning empty DataFrame", exc_info=True)
            return pd.DataFrame()

    def _parse_articles(self, articles: list[dict]) -> pd.DataFrame:
        records = []
        for art in articles:
            tone_str = art.get("tone", "0,0,0,0,0,0,0")
            try:
                tone_parts = [float(x) for x in str(tone_str).split(",")[:7]] if tone_str else [0.0] * 7
            except (TypeError, ValueError):
                tone_parts = [0.0] * 7
            records.append({
                "url": art.get("url", ""),
                "title": art.get("title", ""),
                "seendate": art.get("seendate", ""),
                "domain": art.get("domain", ""),
                "language": art.get("language", ""),
                "sourcecountry": art.get("sourcecountry", ""),
                "tone_avg": tone_parts[0] if len(tone_parts) > 0 else 0.0,
                "tone_pos": tone_parts[1] if len(tone_parts) > 1 else 0.0,
                "tone_neg": tone_parts[2] if len(tone_parts) > 2 else 0.0,
                "polarity": tone_parts[3] if len(tone_parts) > 3 else 0.0,
                "activity_density": tone_parts[4] if len(tone_parts) > 4 else 0.0,
                "word_count": tone_parts[6] if len(tone_parts) > 6 else 0.0,
            })
        return pd.DataFrame(records)

    def _compute_shock_score(self, df: pd.DataFrame) -> float:
        if df.empty:
            return 0.0
        avg_neg_tone = abs(df["tone_neg"].mean()) if "tone_neg" in df.columns else 0.0
        article_count = len(df)
        score = avg_neg_tone * (1 + article_count / 100.0)
        return round(score, 3)

    def _persist_evidence(self, df: pd.DataFrame, *, run_context=None, query_str: str = "") -> int:
        if not run_context or not getattr(run_context, "run_id", None) or df.empty:
            return 0
        persisted = 0
        for row in df.head(MAX_EVIDENCE_DOCUMENTS).to_dict(orient="records"):
            document = normalize_evidence_document(row)
            quality = observation_quality(
                source="GDELT",
                source_id=GDELT_SOURCE_ID,
                available=True,
                authoritative=False,
                execution_eligible=False,
                synthetic=False,
                degraded=False,
                as_of=row.get("seendate"),
                transformation="gdelt_document_normalization",
                transformation_version=1,
            )
            try:
                saved = self.ingest_repo.record_source_observation(
                    ingest_run_id=run_context.run_id,
                    source_id=GDELT_SOURCE_ID,
                    artifact_type="gdelt_article_evidence",
                    artifact_key=document["evidence_id"],
                    observation=document,
                    quality=quality,
                    lineage={
                        "provider": "GDELT DOC API",
                        "transformation": "gdelt_document_normalization",
                        "transformation_version": 1,
                        "query": query_str[:1000],
                    },
                    received_at=getattr(run_context, "received_at", None),
                )
                persisted += int(bool(saved))
            except Exception:
                logger.warning("Failed to persist GDELT evidence document", exc_info=True)
        return persisted

    def _store_results(self, df: pd.DataFrame, shock_score: float) -> None:
        evidence_documents = [
            normalize_evidence_document(row)
            for row in df.head(MAX_EVIDENCE_DOCUMENTS).to_dict(orient="records")
        ]
        self.state_store.set_snapshot("gdelt:latest", {
            "article_count": len(df),
            "shock_score": shock_score,
            "evidence_documents": evidence_documents,
            "evidence_count": len(evidence_documents),
            "evidence_authoritative": False,
            "evidence_type": "news_context",
            "ts": datetime.now(timezone.utc).isoformat(),
        }, ttl=600)

    def _check_shock_spike(self, shock_score: float) -> None:
        if shock_score >= SHOCK_THRESHOLD and self._last_shock_score < SHOCK_THRESHOLD:
            logger.info("GDELT shock spike detected: %.3f (threshold=%.1f)", shock_score, SHOCK_THRESHOLD)
            self.event_bus.emit(
                EventType.SHOCK_SPIKE,
                source="gdelt_ingest",
                payload={
                    "shock_score": shock_score,
                    "threshold": SHOCK_THRESHOLD,
                    "previous": self._last_shock_score,
                },
            )
        self._last_shock_score = shock_score
