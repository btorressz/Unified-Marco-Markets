"""Bounded persistence operations for funding and basis observations."""
import json
from datetime import datetime, timezone
from typing import Any

from backend.core.derivatives_observations import FundingObservation
from backend.data.db import execute_query, execute_returning
from backend.data.repositories.ingest_repo import IngestRepository

MAX_HISTORY_LIMIT = 1000


class DerivativesRepository:
    def __init__(self, ingest_repo=None):
        self.ingest_repo = ingest_repo or IngestRepository()

    def insert_funding(self, observation: FundingObservation, ingest_run_id=None) -> dict | None:
        o = observation
        row = execute_returning(
            """INSERT INTO funding_ticks
               (venue, market, funding_rate, ts, contract_version, source_id, rate_kind,
                raw_funding_rate, normalized_funding_rate, interval_seconds,
                long_cashflow_rate, short_cashflow_rate, annualized_rate,
                provider_timestamp, retrieved_at, timestamp_semantics, sign_convention,
                research_only, execution_eligible, metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
               ON CONFLICT (venue, market, source_id, rate_kind, provider_timestamp)
               WHERE provider_timestamp IS NOT NULL DO NOTHING RETURNING *""",
            (
                o.venue, o.market, o.normalized_funding_rate, o.retrieved_at, o.contract_version,
                o.source_id, o.rate_kind, o.raw_funding_rate, o.normalized_funding_rate,
                o.interval_seconds, o.long_cashflow_rate, o.short_cashflow_rate,
                o.annualized_rate, o.provider_timestamp, o.retrieved_at,
                o.timestamp_semantics, o.sign_convention, o.research_only,
                o.execution_eligible, json.dumps(o.metadata),
            ),
        )
        if row:
            try:
                self.ingest_repo.record_provenance(
                    ingest_run_id, o.source_id, "funding_observation", row.get("id"),
                    artifact_key=f"{o.venue}:{o.market}:{o.rate_kind}",
                    provider_timestamp=o.provider_timestamp, received_at=o.retrieved_at,
                    quality={"contract_version": o.contract_version, "research_only": True},
                    lineage={
                        "provider_field": o.metadata.get("provider_field"),
                        "timestamp_semantics": o.timestamp_semantics,
                    },
                    metadata={
                        "rate_kind": o.rate_kind, "interval_seconds": o.interval_seconds, **o.metadata
                    },
                )
            except Exception:
                pass
        return row

    def funding_history(self, venue=None, market=None, start_ts=None, end_ts=None, limit=200,
                        rate_kind=None, source_id=None, contract_version=1):
        limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
        return execute_query(
            """SELECT * FROM funding_ticks WHERE contract_version = %s
               AND (%s IS NULL OR venue=%s) AND (%s IS NULL OR market=%s)
               AND (%s IS NULL OR rate_kind=%s) AND (%s IS NULL OR source_id=%s)
               AND (%s IS NULL OR COALESCE(provider_timestamp,retrieved_at,ts) >= %s)
               AND (%s IS NULL OR COALESCE(provider_timestamp,retrieved_at,ts) <= %s)
               ORDER BY COALESCE(provider_timestamp,retrieved_at,ts) DESC LIMIT %s""",
            (
                contract_version, venue, venue, market, market, rate_kind, rate_kind,
                source_id, source_id, start_ts, start_ts, end_ts, end_ts, limit,
            ),
        )

    def latest_funding(self, venue, market, rate_kind="current", source_id=None, contract_version=1):
        return self.funding_history(
            venue=venue, market=market, rate_kind=rate_kind,
            source_id=source_id, contract_version=contract_version, limit=1,
        )

    def latest_provider_timestamp(self, venue: str, market: str, rate_kind="realized"):
        rows = execute_query(
            "SELECT MAX(provider_timestamp) AS ts FROM funding_ticks "
            "WHERE contract_version=1 AND venue=%s AND market=%s AND rate_kind=%s",
            (venue, market, rate_kind),
        )
        return rows[0]["ts"] if rows and rows[0].get("ts") else None

    def funding_coverage(self, venue=None, market=None, rate_kind=None, source_id=None):
        return execute_query(
            """SELECT venue, market, rate_kind, source_id, contract_version,
               MIN(COALESCE(provider_timestamp,retrieved_at,ts)) AS first_timestamp,
               MAX(COALESCE(provider_timestamp,retrieved_at,ts)) AS latest_timestamp,
               COUNT(*) AS row_count, COUNT(*) AS count,
               EXTRACT(EPOCH FROM (NOW()-MAX(COALESCE(provider_timestamp,retrieved_at,ts)))) AS age_seconds
               FROM funding_ticks WHERE contract_version=1
               AND (%s IS NULL OR venue=%s) AND (%s IS NULL OR market=%s)
               AND (%s IS NULL OR rate_kind=%s) AND (%s IS NULL OR source_id=%s)
               GROUP BY venue,market,rate_kind,source_id,contract_version
               ORDER BY venue,market,rate_kind,source_id""",
            (venue, venue, market, market, rate_kind, rate_kind, source_id, source_id),
        )

    def _funding_series_coverage(self, venue: str, market: str) -> dict[str, Any]:
        rows = execute_query(
            """SELECT MIN(provider_timestamp) AS first_timestamp,
                      MAX(provider_timestamp) AS latest_timestamp,
                      COUNT(*) AS row_count
               FROM funding_ticks
               WHERE contract_version=1 AND rate_kind='realized'
                 AND venue=%s AND market=%s
                 AND provider_timestamp IS NOT NULL
                 AND normalized_funding_rate IS NOT NULL""",
            (venue, market),
        )
        return rows[0] if rows else {
            "first_timestamp": None, "latest_timestamp": None, "row_count": 0
        }

    def get_funding_event_points_batch(self, *, venue: str, market: str,
                                       event_targets: list[dict[str, Any]]) -> dict[str, Any]:
        """Return bounded realized-v1 points for all events in one series query."""
        coverage = self._funding_series_coverage(venue, market)
        if not event_targets:
            return {
                "rows": [], "coverage": coverage, "truncated": False,
                "query_mode": "event_target_lateral_v1", "requested_target_count": 0,
            }
        payload = json.dumps(event_targets, default=str)
        rows = execute_query(
            """WITH targets AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb)
                     AS t(event_id text,event_ts timestamptz,horizon text,target_ts timestamptz)
               ), events AS (
                   SELECT DISTINCT event_id,event_ts FROM targets
               ), refs AS (
                   SELECT e.event_id,'reference'::text AS point_kind,NULL::text AS horizon,f.*
                   FROM events e
                   LEFT JOIN LATERAL (
                       SELECT * FROM funding_ticks f
                       WHERE f.contract_version=1 AND f.rate_kind='realized'
                         AND f.venue=%s AND f.market=%s
                         AND f.provider_timestamp IS NOT NULL
                         AND f.normalized_funding_rate IS NOT NULL
                         AND f.provider_timestamp<=e.event_ts
                       ORDER BY f.provider_timestamp DESC,f.id DESC LIMIT 1
                   ) f ON TRUE
               ), hits AS (
                   SELECT t.event_id,'target'::text AS point_kind,t.horizon,f.*
                   FROM targets t
                   LEFT JOIN LATERAL (
                       SELECT * FROM funding_ticks f
                       WHERE f.contract_version=1 AND f.rate_kind='realized'
                         AND f.venue=%s AND f.market=%s
                         AND f.provider_timestamp IS NOT NULL
                         AND f.normalized_funding_rate IS NOT NULL
                         AND f.provider_timestamp>=t.target_ts
                       ORDER BY f.provider_timestamp ASC,f.id ASC LIMIT 1
                   ) f ON TRUE
               )
               SELECT * FROM refs
               UNION ALL
               SELECT * FROM hits
               ORDER BY event_id,point_kind,horizon NULLS FIRST""",
            (payload, venue, market, venue, market),
        )
        return {
            "rows": rows, "coverage": coverage, "truncated": False,
            "query_mode": "event_target_lateral_v1",
            "requested_target_count": len(event_targets),
            "max_expected_rows": len({str(row["event_id"]) for row in event_targets}) + len(event_targets),
        }

    def insert_basis(self, observation: dict, ingest_run_id=None) -> dict | None:
        row = execute_returning(
            """INSERT INTO basis_observations
               (contract_version,symbol,venue,market,spot_source,spot_price,perp_price,
                basis_bps,spot_ts,perp_ts,observed_at,retrieved_at,timestamp_skew_seconds,
                aligned,fresh,research_only,execution_eligible,lineage,metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
               ON CONFLICT (venue,market,spot_source,spot_ts,perp_ts) DO NOTHING RETURNING *""",
            (
                observation["contract_version"], observation["symbol"], observation["venue"],
                observation["market"], observation["spot_source"], observation["spot_price"],
                observation["perp_price"], observation["basis_bps"], observation["spot_ts"],
                observation["perp_ts"], observation["observed_at"], observation["retrieved_at"],
                observation["timestamp_skew_seconds"], observation["aligned"], observation["fresh"],
                True, False, json.dumps(observation.get("lineage", {})),
                json.dumps(observation.get("metadata", {})),
            ),
        )
        if row:
            try:
                self.ingest_repo.record_provenance(
                    ingest_run_id, "basis_materializer_v1", "basis_observation", row.get("id"),
                    artifact_key=f'{observation["venue"]}:{observation["market"]}',
                    provider_timestamp=observation["observed_at"], received_at=observation["retrieved_at"],
                    quality={
                        "aligned": True, "fresh": True,
                        "timestamp_skew_seconds": observation["timestamp_skew_seconds"],
                    },
                    lineage=observation.get("lineage", {}),
                    metadata=observation.get("metadata", {}),
                )
            except Exception:
                pass
        return row

    def basis_history(self, symbol=None, venue=None, market=None, start_ts=None, end_ts=None, limit=200):
        limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
        return execute_query(
            """SELECT * FROM basis_observations WHERE (%s IS NULL OR symbol=%s)
               AND (%s IS NULL OR venue=%s) AND (%s IS NULL OR market=%s)
               AND (%s IS NULL OR observed_at >= %s) AND (%s IS NULL OR observed_at <= %s)
               ORDER BY observed_at DESC LIMIT %s""",
            (
                symbol, symbol, venue, venue, market, market,
                start_ts, start_ts, end_ts, end_ts, limit,
            ),
        )

    def basis_coverage(self, symbol=None, venue=None, market=None):
        return execute_query(
            """SELECT symbol,venue,market,MIN(observed_at) first_timestamp,
                      MAX(observed_at) latest_timestamp,COUNT(*) count,
                      EXTRACT(EPOCH FROM (NOW()-MAX(observed_at))) age_seconds
               FROM basis_observations
               WHERE (%s IS NULL OR symbol=%s) AND (%s IS NULL OR venue=%s)
                 AND (%s IS NULL OR market=%s)
               GROUP BY symbol,venue,market ORDER BY symbol,venue""",
            (symbol, symbol, venue, venue, market, market),
        )

    def _basis_series_coverage(self, symbol: str, venue: str, market: str) -> dict[str, Any]:
        rows = execute_query(
            """SELECT MIN(observed_at) AS first_timestamp,
                      MAX(observed_at) AS latest_timestamp,
                      COUNT(*) AS row_count
               FROM basis_observations
               WHERE symbol=%s AND venue=%s AND market=%s
                 AND basis_bps IS NOT NULL AND aligned=true AND fresh=true""",
            (symbol, venue, market),
        )
        return rows[0] if rows else {
            "first_timestamp": None, "latest_timestamp": None, "row_count": 0
        }

    def get_basis_event_points_batch(self, *, symbol: str, venue: str, market: str,
                                     event_targets: list[dict[str, Any]]) -> dict[str, Any]:
        """Return bounded durable basis points for all events in one series query."""
        coverage = self._basis_series_coverage(symbol, venue, market)
        if not event_targets:
            return {
                "rows": [], "coverage": coverage, "truncated": False,
                "query_mode": "event_target_lateral_v1", "requested_target_count": 0,
            }
        payload = json.dumps(event_targets, default=str)
        rows = execute_query(
            """WITH targets AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb)
                     AS t(event_id text,event_ts timestamptz,horizon text,target_ts timestamptz)
               ), events AS (
                   SELECT DISTINCT event_id,event_ts FROM targets
               ), refs AS (
                   SELECT e.event_id,'reference'::text AS point_kind,NULL::text AS horizon,b.*
                   FROM events e
                   LEFT JOIN LATERAL (
                       SELECT * FROM basis_observations b
                       WHERE b.symbol=%s AND b.venue=%s AND b.market=%s
                         AND b.basis_bps IS NOT NULL AND b.aligned=true AND b.fresh=true
                         AND b.observed_at<=e.event_ts
                       ORDER BY b.observed_at DESC,b.id DESC LIMIT 1
                   ) b ON TRUE
               ), hits AS (
                   SELECT t.event_id,'target'::text AS point_kind,t.horizon,b.*
                   FROM targets t
                   LEFT JOIN LATERAL (
                       SELECT * FROM basis_observations b
                       WHERE b.symbol=%s AND b.venue=%s AND b.market=%s
                         AND b.basis_bps IS NOT NULL AND b.aligned=true AND b.fresh=true
                         AND b.observed_at>=t.target_ts
                       ORDER BY b.observed_at ASC,b.id ASC LIMIT 1
                   ) b ON TRUE
               )
               SELECT * FROM refs
               UNION ALL
               SELECT * FROM hits
               ORDER BY event_id,point_kind,horizon NULLS FIRST""",
            (payload, symbol, venue, market, symbol, venue, market),
        )
        return {
            "rows": rows, "coverage": coverage, "truncated": False,
            "query_mode": "event_target_lateral_v1",
            "requested_target_count": len(event_targets),
            "max_expected_rows": len({str(row["event_id"]) for row in event_targets}) + len(event_targets),
        }

    def get_funding_event_points(self, *, venue, market, event_ts, horizon_targets,
                                 reference_max_age_seconds=86400, target_lag_seconds=7200):
        """Select one realized v1 reference and at most one row per target."""
        return execute_query(
            """(SELECT * FROM funding_ticks WHERE contract_version=1 AND rate_kind='realized'
               AND venue=%s AND market=%s AND provider_timestamp IS NOT NULL
               AND normalized_funding_rate IS NOT NULL AND provider_timestamp<=%s
               AND provider_timestamp>=%s-(%s * interval '1 second')
               ORDER BY provider_timestamp DESC,id DESC LIMIT 1)
               UNION ALL
               SELECT hit.* FROM unnest(%s::timestamptz[]) target
               CROSS JOIN LATERAL (SELECT * FROM funding_ticks WHERE contract_version=1 AND rate_kind='realized'
                   AND venue=%s AND market=%s AND provider_timestamp IS NOT NULL
                   AND normalized_funding_rate IS NOT NULL AND provider_timestamp>=target
                   AND provider_timestamp<=target+(%s * interval '1 second')
                   ORDER BY provider_timestamp ASC,id ASC LIMIT 1) hit""",
            (
                venue, market, event_ts, event_ts, reference_max_age_seconds, list(horizon_targets),
                venue, market, target_lag_seconds,
            ),
        )

    def get_basis_event_points(self, *, symbol, venue, market, event_ts, horizon_targets,
                               reference_max_age_seconds=86400, target_lag_seconds=7200):
        """Select targeted durable basis points without loading minute history."""
        return execute_query(
            """(SELECT * FROM basis_observations WHERE symbol=%s AND venue=%s AND market=%s
               AND basis_bps IS NOT NULL AND aligned=true AND fresh=true AND observed_at<=%s
               AND observed_at>=%s-(%s * interval '1 second')
               ORDER BY observed_at DESC,id DESC LIMIT 1)
               UNION ALL
               SELECT hit.* FROM unnest(%s::timestamptz[]) target
               CROSS JOIN LATERAL (SELECT * FROM basis_observations WHERE symbol=%s AND venue=%s AND market=%s
                   AND basis_bps IS NOT NULL AND aligned=true AND fresh=true AND observed_at>=target
                   AND observed_at<=target+(%s * interval '1 second')
                   ORDER BY observed_at ASC,id ASC LIMIT 1) hit""",
            (
                symbol, venue, market, event_ts, event_ts, reference_max_age_seconds, list(horizon_targets),
                symbol, venue, market, target_lag_seconds,
            ),
        )
