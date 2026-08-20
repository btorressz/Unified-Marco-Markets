"""Bounded persistence operations for funding and basis observations."""
import json
from datetime import datetime, timezone

from backend.core.derivatives_observations import FundingObservation
from backend.data.db import execute_query, execute_returning

MAX_HISTORY_LIMIT = 1000


class DerivativesRepository:
    def insert_funding(self, observation: FundingObservation) -> dict | None:
        o = observation
        return execute_returning(
            """INSERT INTO funding_ticks
               (venue, market, funding_rate, ts, contract_version, source_id, rate_kind,
                raw_funding_rate, normalized_funding_rate, interval_seconds,
                long_cashflow_rate, short_cashflow_rate, annualized_rate,
                provider_timestamp, retrieved_at, timestamp_semantics, sign_convention,
                research_only, execution_eligible, metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
               ON CONFLICT (venue, market, source_id, rate_kind, provider_timestamp)
               WHERE provider_timestamp IS NOT NULL DO NOTHING RETURNING *""",
            (o.venue, o.market, o.normalized_funding_rate, o.retrieved_at, o.contract_version,
             o.source_id, o.rate_kind, o.raw_funding_rate, o.normalized_funding_rate,
             o.interval_seconds, o.long_cashflow_rate, o.short_cashflow_rate,
             o.annualized_rate, o.provider_timestamp, o.retrieved_at,
             o.timestamp_semantics, o.sign_convention, o.research_only,
             o.execution_eligible, json.dumps(o.metadata)),
        )

    def funding_history(self, venue=None, market=None, start_ts=None, end_ts=None, limit=200):
        limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
        return execute_query(
            """SELECT * FROM funding_ticks WHERE contract_version = 1
               AND (%s IS NULL OR venue=%s) AND (%s IS NULL OR market=%s)
               AND (%s IS NULL OR provider_timestamp >= %s)
               AND (%s IS NULL OR provider_timestamp <= %s)
               ORDER BY provider_timestamp DESC NULLS LAST, ts DESC LIMIT %s""",
            (venue, venue, market, market, start_ts, start_ts, end_ts, end_ts, limit),
        )

    def latest_funding(self, venue=None, market=None):
        return self.funding_history(venue=venue, market=market, limit=1)

    def latest_provider_timestamp(self, venue: str, market: str, rate_kind="realized"):
        rows = execute_query(
            "SELECT MAX(provider_timestamp) AS ts FROM funding_ticks WHERE contract_version=1 AND venue=%s AND market=%s AND rate_kind=%s",
            (venue, market, rate_kind),
        )
        return rows[0]["ts"] if rows and rows[0].get("ts") else None

    def funding_coverage(self, venue=None, market=None):
        return execute_query(
            """SELECT venue, market, MIN(provider_timestamp) AS first_timestamp,
               MAX(provider_timestamp) AS latest_timestamp, COUNT(*) AS count,
               EXTRACT(EPOCH FROM (NOW()-MAX(provider_timestamp))) AS age_seconds
               FROM funding_ticks WHERE contract_version=1
               AND (%s IS NULL OR venue=%s) AND (%s IS NULL OR market=%s)
               GROUP BY venue, market ORDER BY venue, market""", (venue, venue, market, market))

    def insert_basis(self, observation: dict) -> dict | None:
        return execute_returning(
            """INSERT INTO basis_observations
               (contract_version,symbol,venue,market,spot_source,spot_price,perp_price,
                basis_bps,spot_ts,perp_ts,observed_at,retrieved_at,timestamp_skew_seconds,
                aligned,fresh,research_only,execution_eligible,lineage,metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
               ON CONFLICT (venue,market,spot_source,spot_ts,perp_ts) DO NOTHING RETURNING *""",
            (observation["contract_version"], observation["symbol"], observation["venue"],
             observation["market"], observation["spot_source"], observation["spot_price"],
             observation["perp_price"], observation["basis_bps"], observation["spot_ts"],
             observation["perp_ts"], observation["observed_at"], observation["retrieved_at"],
             observation["timestamp_skew_seconds"], observation["aligned"], observation["fresh"],
             True, False, json.dumps(observation.get("lineage", {})), json.dumps(observation.get("metadata", {}))))

    def basis_history(self, symbol=None, market=None, limit=200):
        limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
        return execute_query("""SELECT * FROM basis_observations WHERE (%s IS NULL OR symbol=%s)
            AND (%s IS NULL OR market=%s) ORDER BY observed_at DESC LIMIT %s""",
            (symbol, symbol, market, market, limit))

    def basis_coverage(self, symbol=None, market=None):
        return execute_query("""SELECT symbol,venue,market,MIN(observed_at) first_timestamp,
            MAX(observed_at) latest_timestamp,COUNT(*) count,
            EXTRACT(EPOCH FROM (NOW()-MAX(observed_at))) age_seconds FROM basis_observations
            WHERE (%s IS NULL OR symbol=%s) AND (%s IS NULL OR market=%s)
            GROUP BY symbol,venue,market ORDER BY symbol,venue""", (symbol,symbol,market,market))
