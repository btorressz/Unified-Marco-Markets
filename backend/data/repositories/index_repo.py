import json
import logging
from datetime import datetime, timezone

from backend.data.db import execute_query, execute_returning

logger = logging.getLogger(__name__)


class IndexRepository:

    def save_index(
        self,
        index_level: float,
        roc: float,
        shock: float,
        components: dict | None = None,
        lineage: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO index_history (index_level, rate_of_change, shock_score, components, ts)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id, index_level, rate_of_change, shock_score, components, ts""",
                (index_level, roc, shock, json.dumps(components or {}), datetime.now(timezone.utc)),
            )
            if row and lineage:
                try:
                    from backend.data.repositories.ingest_repo import IngestRepository
                    IngestRepository().record_provenance(lineage.get("ingest_run_id"), lineage.get("source_id", "derived_index"), "index_snapshot", artifact_id=row.get("id"), lineage=lineage)
                except Exception:
                    logger.warning("Failed to record index snapshot provenance", exc_info=True)
            return row
        except Exception:
            logger.error("Failed to save index", exc_info=True)
            return None

    def get_latest(self) -> dict | None:
        try:
            rows = execute_query(
                "SELECT id, index_level, rate_of_change, shock_score, components, ts FROM index_history ORDER BY ts DESC LIMIT 1"
            )
            return rows[0] if rows else None
        except Exception:
            logger.error("Failed to get latest index", exc_info=True)
            return None

    def get_history(self, window_seconds: int = 86400) -> list[dict]:
        try:
            return execute_query(
                """SELECT id, index_level, rate_of_change, shock_score, components, ts
                   FROM index_history
                   WHERE ts >= NOW() - INTERVAL '%s seconds'
                   ORDER BY ts ASC""",
                (window_seconds,),
            )
        except Exception:
            logger.error("Failed to get index history", exc_info=True)
            return []

    def get_components(self) -> list[dict]:
        try:
            rows = execute_query(
                "SELECT components, ts FROM index_history ORDER BY ts DESC LIMIT 1"
            )
            if rows and rows[0].get("components"):
                comp = rows[0]["components"]
                if isinstance(comp, str):
                    comp = json.loads(comp)
                return [{"name": k, "value": v, "ts": rows[0]["ts"]} for k, v in comp.items()]
            return []
        except Exception:
            logger.error("Failed to get index components", exc_info=True)
            return []
