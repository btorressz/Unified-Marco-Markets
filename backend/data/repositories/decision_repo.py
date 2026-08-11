"""Persistence boundary for immutable decision audit records."""
from __future__ import annotations

import json
from typing import Any


def _db():
    from backend.data import db
    return db


_JSON_FIELDS = (
    "input_state", "input_provenance", "derived_state", "heuristic_result",
    "ml_result", "risk_result", "allocation_result", "execution_intent",
    "component_versions", "config_snapshot", "final_decision",
)


class DecisionRepository:
    """Small repository kept separate from execution and order persistence."""

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        columns = ("id", "decision_ts", "decision_type", "venue", "market", "symbol") + _JSON_FIELDS + ("decision_hash",)
        values = [row.get(name) for name in columns]
        for index, name in enumerate(columns):
            if name in _JSON_FIELDS:
                values[index] = json.dumps(values[index] or {}, default=str)
        json_casts = {name: "%s::jsonb" for name in _JSON_FIELDS}
        placeholders = ",".join(json_casts.get(name, "%s") for name in columns)
        sql = f"INSERT INTO decision_audit ({','.join(columns)}) VALUES ({placeholders}) RETURNING *"
        return _db().execute_returning(sql, tuple(values))

    # Compatibility alias for callers that use persistence-oriented naming.
    save = create

    def get(self, decision_id: str) -> dict[str, Any] | None:
        rows = _db().execute_query("SELECT * FROM decision_audit WHERE id=%s", (decision_id,))
        return rows[0] if rows else None

    get_decision = get

    def list(self, *, decision_type: str | None = None, venue: str | None = None,
             market: str | None = None, start_ts=None, end_ts=None,
             limit: int = 50) -> list[dict[str, Any]]:
        clauses, params = [], []
        for column, value in (("decision_type", decision_type), ("venue", venue), ("market", market)):
            if value is not None:
                clauses.append(f"{column}=%s")
                params.append(value)
        if start_ts is not None:
            clauses.append("decision_ts >= %s")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("decision_ts <= %s")
            params.append(end_ts)
        safe_limit = max(1, min(int(limit), 200))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(safe_limit)
        return _db().execute_query(
            f"SELECT * FROM decision_audit{where} ORDER BY decision_ts DESC, created_at DESC LIMIT %s",
            tuple(params),
        )

    list_decisions = list
