import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

from backend.config import GDELT_KEYWORDS
from backend.core.event_bus import EventBus, EventType
from backend.core.state_store import StateStore

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
SHOCK_THRESHOLD = 5.0


class GDELTIngestor:

    def __init__(self, event_bus: EventBus | None = None, state_store: StateStore | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
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
                    if run_context: run_context.mark_success()
                    return pd.DataFrame()

                df = self._parse_articles(articles)
                if run_context: run_context.mark_success(); run_context.record_received(len(df))
                shock_score = self._compute_shock_score(df)
                self._store_results(df, shock_score)
                if run_context: run_context.record_persisted(len(df))
                self._check_shock_spike(shock_score)
                return df
        except Exception as exc:
            if run_context: run_context.mark_failure(exc)
            logger.warning("GDELT API failed, returning empty DataFrame", exc_info=True)
            return pd.DataFrame()

    def _parse_articles(self, articles: list[dict]) -> pd.DataFrame:
        records = []
        for art in articles:
            tone_str = art.get("tone", "0,0,0,0,0,0,0")
            tone_parts = [float(x) for x in str(tone_str).split(",")[:7]] if tone_str else [0.0] * 7
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

    def _store_results(self, df: pd.DataFrame, shock_score: float) -> None:
        self.state_store.set_snapshot("gdelt:latest", {
            "article_count": len(df),
            "shock_score": shock_score,
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
