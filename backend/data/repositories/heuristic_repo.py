from __future__ import annotations
import json
from datetime import datetime
from typing import Any
import psycopg2.extras
from backend.data.db import get_connection, release_connection, execute_query


def _normal(row):
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, datetime): out[k] = v.isoformat()
    return out


class HeuristicRepository:
    def bulk_upsert(self, rows: list[dict[str, Any]]) -> int:
        if not rows: return 0
        columns = ("heuristic_id", "heuristic_version", "evaluation_type", "action_type", "expected_direction", "venue", "market", "symbol", "decision_ts", "price_at_decision", "fired", "confidence", "expected_return", "context", "regime", "outcomes", "primary_horizon", "primary_return", "signed_primary_return", "directional_hit", "evaluation_status", "missing_context", "source")
        values = [tuple(json.dumps(r.get(c), default=str) if c in {"context","regime","outcomes","missing_context"} else r.get(c) for c in columns) for r in rows]
        sql = f"""INSERT INTO heuristic_evaluations ({','.join(columns)}) VALUES %s
          ON CONFLICT (heuristic_id, heuristic_version, venue, market, decision_ts, primary_horizon)
          DO UPDATE SET symbol=EXCLUDED.symbol, price_at_decision=EXCLUDED.price_at_decision, fired=EXCLUDED.fired,
          context=EXCLUDED.context, regime=EXCLUDED.regime, outcomes=EXCLUDED.outcomes, primary_return=EXCLUDED.primary_return,
          signed_primary_return=EXCLUDED.signed_primary_return, directional_hit=EXCLUDED.directional_hit,
          evaluation_status=EXCLUDED.evaluation_status, missing_context=EXCLUDED.missing_context, updated_at=NOW()"""
        conn = get_connection()
        try:
            with conn.cursor() as cur: psycopg2.extras.execute_values(cur, sql, values, page_size=500)
            return len(rows)
        finally: release_connection(conn)

    def query(self, *, heuristic_id=None, version=None, fired=None, primary_horizon=None, start_ts=None, end_ts=None, venue=None, market=None, limit=1000):
        clauses, params = [], []
        for col, val in (("heuristic_id",heuristic_id),("heuristic_version",version),("fired",fired),("primary_horizon",primary_horizon),("venue",venue),("market",market)):
            if val is not None: clauses.append(f"{col} = %s"); params.append(val)
        if start_ts: clauses.append("decision_ts >= %s::timestamptz"); params.append(start_ts)
        if end_ts: clauses.append("decision_ts <= %s::timestamptz"); params.append(end_ts)
        params.append(max(1, min(int(limit), 5000)))
        rows = execute_query(f"SELECT * FROM heuristic_evaluations {'WHERE ' + ' AND '.join(clauses) if clauses else ''} ORDER BY decision_ts DESC LIMIT %s", params)
        return [_normal(r) for r in rows]

    def performance_rows(self, **filters):
        return self.query(**filters, limit=5000)
