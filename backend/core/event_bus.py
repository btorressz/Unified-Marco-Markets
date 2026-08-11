import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras

from backend.core.redis_runtime import RedisRuntime, get_redis_runtime

logger = logging.getLogger(__name__)


class EventType:
    INDEX_UPDATE = "INDEX_UPDATE"
    SHOCK_SPIKE = "SHOCK_SPIKE"
    DIVERGENCE_ALERT = "DIVERGENCE_ALERT"
    FUNDING_REGIME_FLIP = "FUNDING_REGIME_FLIP"
    RISK_THROTTLE_ON = "RISK_THROTTLE_ON"
    RISK_THROTTLE_OFF = "RISK_THROTTLE_OFF"
    RULE_ACTION_PROPOSED = "RULE_ACTION_PROPOSED"
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    ORDER_RISK_APPROVED = "ORDER_RISK_APPROVED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_OPEN = "ORDER_OPEN"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCEL_PENDING = "ORDER_CANCEL_PENDING"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_SUBMISSION_UNKNOWN = "ORDER_SUBMISSION_UNKNOWN"
    # Compatibility aliases retained for existing consumers.
    ORDER_SENT = "ORDER_SENT"
    ORDER_EXECUTION_STATE_UNKNOWN = "ORDER_EXECUTION_STATE_UNKNOWN"
    SWAP_QUOTED = "SWAP_QUOTED"
    SWAP_SENT = "SWAP_SENT"
    ERROR = "ERROR"
    STABLE_DEPEG_ALERT = "STABLE_DEPEG_ALERT"
    STABLE_VOLUME_SPIKE = "STABLE_VOLUME_SPIKE"
    STABLE_FUNDING_SPIKE = "STABLE_FUNDING_SPIKE"
    STABLE_STRESS_ALERT = "STABLE_STRESS_ALERT"
    PEG_BREAK_PROB_UPDATE = "PEG_BREAK_PROB_UPDATE"
    PREDICTION_UPDATE = "PREDICTION_UPDATE"
    PREDICTION_CONFIDENCE_LOW = "PREDICTION_CONFIDENCE_LOW"
    MONTE_CARLO_RUN = "MONTE_CARLO_RUN"
    RISK_VAR_BREACH = "RISK_VAR_BREACH"
    MICROSTRUCTURE_SIGNAL = "MICROSTRUCTURE_SIGNAL"
    DISLOCATION_ALERT = "DISLOCATION_ALERT"
    CARRY_UPDATE = "CARRY_UPDATE"
    CARRY_REGIME_FLIP = "CARRY_REGIME_FLIP"
    AGENT_SIGNAL = "AGENT_SIGNAL"
    AGENT_ACTION_PROPOSED = "AGENT_ACTION_PROPOSED"
    AGENT_BLOCKED = "AGENT_BLOCKED"
    MACRO_TERMINAL_UPDATE = "MACRO_TERMINAL_UPDATE"
    PRICE_DISLOCATION_ALERT = "PRICE_DISLOCATION_ALERT"
    PNL_ATTRIBUTION_UPDATE = "PNL_ATTRIBUTION_UPDATE"
    REGIME_MEMORY_UPDATE = "REGIME_MEMORY_UPDATE"
    EXECUTION_METRICS_UPDATE = "EXECUTION_METRICS_UPDATE"
    SLIPPAGE_ANOMALY_ALERT = "SLIPPAGE_ANOMALY_ALERT"
    SOLANA_CONGESTION_WARNING = "SOLANA_CONGESTION_WARNING"
    JUPITER_ROUTE_RISK = "JUPITER_ROUTE_RISK"
    EXECUTION_THROTTLE = "EXECUTION_THROTTLE"
    FUNDING_ARB_OPPORTUNITY = "FUNDING_ARB_OPPORTUNITY"
    FUNDING_ARB_REGIME_FLIP = "FUNDING_ARB_REGIME_FLIP"
    BASIS_UPDATE = "BASIS_UPDATE"
    BASIS_OPPORTUNITY = "BASIS_OPPORTUNITY"
    BASIS_FEASIBILITY_LOW = "BASIS_FEASIBILITY_LOW"
    LIQUIDITY_THINNING_WARNING = "LIQUIDITY_THINNING_WARNING"
    STABLE_FLOW_UPDATE = "STABLE_FLOW_UPDATE"
    ADAPTIVE_WEIGHTS_UPDATE = "ADAPTIVE_WEIGHTS_UPDATE"
    REGIME_ANALOG_MATCH = "REGIME_ANALOG_MATCH"
    PORTFOLIO_PROPOSAL = "PORTFOLIO_PROPOSAL"
    LIQUIDATION_HEATMAP_UPDATE = "LIQUIDATION_HEATMAP_UPDATE"
    JUPITER_QUOTE_STALE = "JUPITER_QUOTE_STALE"
    JUPITER_SLIPPAGE_SPIKE = "JUPITER_SLIPPAGE_SPIKE"
    HEDGE_PROPOSAL = "HEDGE_PROPOSAL"
    HEDGE_REBALANCE_SUGGESTED = "HEDGE_REBALANCE_SUGGESTED"
    HEDGE_THROTTLE_RECOMMENDED = "HEDGE_THROTTLE_RECOMMENDED"
    SANDBOX_COMPARISON_RUN = "SANDBOX_COMPARISON_RUN"
    REPLAY_COMPLETED = "REPLAY_COMPLETED"
    SLIPPAGE_MODEL_UPDATE = "SLIPPAGE_MODEL_UPDATE"
    SAFE_SIZE_WARNING = "SAFE_SIZE_WARNING"
    HEDGE_RATIO_UPDATE = "HEDGE_RATIO_UPDATE"
    STABLECOIN_PLAYBOOK_TRIGGERED = "STABLECOIN_PLAYBOOK_TRIGGERED"
    TRADE_BLOCKED_STALE_DATA = "TRADE_BLOCKED_STALE_DATA"
    TRADE_DEGRADED_DATA = "TRADE_DEGRADED_DATA"
    CAPITAL_ALLOCATION_UPDATE = "CAPITAL_ALLOCATION_UPDATE"
    REBALANCE_PREVIEW_CREATED = "REBALANCE_PREVIEW_CREATED"
    ML_FEATURES_UPDATED = "ML_FEATURES_UPDATED"
    ML_MODEL_TRAINED = "ML_MODEL_TRAINED"
    ML_INFERENCE_UPDATE = "ML_INFERENCE_UPDATE"
    BACKTEST_STARTED = "BACKTEST_STARTED"
    BACKTEST_COMPLETED = "BACKTEST_COMPLETED"
    VOL_REGIME_CHANGED = "VOL_REGIME_CHANGED"
    PORTFOLIO_RISK_UPDATE = "PORTFOLIO_RISK_UPDATE"
    REDIS_DEGRADED = "REDIS_DEGRADED"
    REDIS_RECOVERED = "REDIS_RECOVERED"
    # Phase 7 — Execution + Risk Intelligence
    ALLOCATION_SIZE_ADJUSTED = "ALLOCATION_SIZE_ADJUSTED"
    ALLOCATION_LIMIT_BREACH = "ALLOCATION_LIMIT_BREACH"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    TAKE_PROFIT_TRIGGERED = "TAKE_PROFIT_TRIGGERED"
    TRAILING_STOP_UPDATED = "TRAILING_STOP_UPDATED"
    BRACKET_ORDER_CREATED = "BRACKET_ORDER_CREATED"
    ADVANCED_ORDER_REJECTED = "ADVANCED_ORDER_REJECTED"
    REDUCE_ONLY_REJECTED = "REDUCE_ONLY_REJECTED"
    TWAP_STARTED = "TWAP_STARTED"
    TWAP_SLICE_FILLED = "TWAP_SLICE_FILLED"
    VWAP_STARTED = "VWAP_STARTED"
    VWAP_SLICE_FILLED = "VWAP_SLICE_FILLED"
    SMART_EXECUTION_COMPLETED = "SMART_EXECUTION_COMPLETED"
    SMART_EXECUTION_ABORTED = "SMART_EXECUTION_ABORTED"
    STRATEGY_PERFORMANCE_UPDATE = "STRATEGY_PERFORMANCE_UPDATE"
    FEED_STALE = "FEED_STALE"
    FEED_ERROR = "FEED_ERROR"
    FEED_RECOVERED = "FEED_RECOVERED"
    PRICE_AUTHORITY_CHANGED = "PRICE_AUTHORITY_CHANGED"
    TRADE_DEBUG_REPLAY_RUN = "TRADE_DEBUG_REPLAY_RUN"
    DECISION_RECORDED = "DECISION_RECORDED"
    DECISION_REPLAYED = "DECISION_REPLAYED"
    DECISION_REPLAY_MISMATCH = "DECISION_REPLAY_MISMATCH"

    ALL = [
        INDEX_UPDATE, SHOCK_SPIKE, DIVERGENCE_ALERT, FUNDING_REGIME_FLIP,
        RISK_THROTTLE_ON, RISK_THROTTLE_OFF, RULE_ACTION_PROPOSED,
        ORDER_INTENT_CREATED, ORDER_RISK_APPROVED, ORDER_SUBMITTED,
        ORDER_ACKNOWLEDGED, ORDER_OPEN, ORDER_PARTIALLY_FILLED,
        ORDER_FILLED, ORDER_CANCEL_PENDING, ORDER_CANCELLED,
        ORDER_REJECTED, ORDER_SUBMISSION_UNKNOWN,
        ORDER_SENT, ORDER_EXECUTION_STATE_UNKNOWN,
        SWAP_QUOTED, SWAP_SENT, ERROR,
        STABLE_DEPEG_ALERT, STABLE_VOLUME_SPIKE, STABLE_FUNDING_SPIKE,
        STABLE_STRESS_ALERT, PEG_BREAK_PROB_UPDATE,
        PREDICTION_UPDATE, PREDICTION_CONFIDENCE_LOW,
        MONTE_CARLO_RUN, RISK_VAR_BREACH,
        MICROSTRUCTURE_SIGNAL, DISLOCATION_ALERT,
        CARRY_UPDATE, CARRY_REGIME_FLIP,
        AGENT_SIGNAL, AGENT_ACTION_PROPOSED, AGENT_BLOCKED,
        MACRO_TERMINAL_UPDATE, PRICE_DISLOCATION_ALERT,
        PNL_ATTRIBUTION_UPDATE, REGIME_MEMORY_UPDATE,
        EXECUTION_METRICS_UPDATE, SLIPPAGE_ANOMALY_ALERT,
        SOLANA_CONGESTION_WARNING, JUPITER_ROUTE_RISK, EXECUTION_THROTTLE,
        FUNDING_ARB_OPPORTUNITY, FUNDING_ARB_REGIME_FLIP,
        BASIS_UPDATE, BASIS_OPPORTUNITY, BASIS_FEASIBILITY_LOW,
        LIQUIDITY_THINNING_WARNING, STABLE_FLOW_UPDATE,
        ADAPTIVE_WEIGHTS_UPDATE, REGIME_ANALOG_MATCH,
        PORTFOLIO_PROPOSAL, LIQUIDATION_HEATMAP_UPDATE,
        JUPITER_QUOTE_STALE, JUPITER_SLIPPAGE_SPIKE,
        HEDGE_PROPOSAL, HEDGE_REBALANCE_SUGGESTED, HEDGE_THROTTLE_RECOMMENDED,
        SANDBOX_COMPARISON_RUN, REPLAY_COMPLETED,
        SLIPPAGE_MODEL_UPDATE, SAFE_SIZE_WARNING,
        HEDGE_RATIO_UPDATE, STABLECOIN_PLAYBOOK_TRIGGERED,
        TRADE_BLOCKED_STALE_DATA, TRADE_DEGRADED_DATA,
        CAPITAL_ALLOCATION_UPDATE, REBALANCE_PREVIEW_CREATED,
        ML_FEATURES_UPDATED, ML_MODEL_TRAINED, ML_INFERENCE_UPDATE,
        BACKTEST_STARTED, BACKTEST_COMPLETED,
        VOL_REGIME_CHANGED, PORTFOLIO_RISK_UPDATE,
        REDIS_DEGRADED, REDIS_RECOVERED,
        # Phase 7
        ALLOCATION_SIZE_ADJUSTED, ALLOCATION_LIMIT_BREACH,
        STOP_LOSS_TRIGGERED, TAKE_PROFIT_TRIGGERED,
        TRAILING_STOP_UPDATED, BRACKET_ORDER_CREATED,
        ADVANCED_ORDER_REJECTED, REDUCE_ONLY_REJECTED,
        TWAP_STARTED, TWAP_SLICE_FILLED,
        VWAP_STARTED, VWAP_SLICE_FILLED,
        SMART_EXECUTION_COMPLETED, SMART_EXECUTION_ABORTED,
        STRATEGY_PERFORMANCE_UPDATE,
        FEED_STALE, FEED_ERROR, FEED_RECOVERED, PRICE_AUTHORITY_CHANGED,
        TRADE_DEBUG_REPLAY_RUN,
        DECISION_RECORDED, DECISION_REPLAYED, DECISION_REPLAY_MISMATCH,
    ]


CHANNEL = "desk:events"


class EventBus:

    def __init__(
        self,
        redis_url: str | None = None,
        database_url: str | None = None,
        redis_runtime: RedisRuntime | None = None,
    ):
        if redis_runtime is not None:
            self._redis_runtime = redis_runtime
        elif redis_url:
            self._redis_runtime = RedisRuntime(redis_url=redis_url)
        else:
            self._redis_runtime = get_redis_runtime()
        self._redis_url = self._redis_runtime.redis_url
        self._database_url = database_url or os.environ.get("DATABASE_URL", "")

    def _get_redis(self):
        return self._redis_runtime.get_client()

    def _get_pg_conn(self):
        if not self._database_url:
            return None
        try:
            conn = psycopg2.connect(self._database_url)
            conn.autocommit = True
            return conn
        except Exception:
            logger.warning("Postgres unavailable, event persistence disabled", exc_info=True)
            return None

    def emit(self, event_type: str, source: str, payload: dict[str, Any] | None = None) -> str:
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        payload = payload or {}

        event_data = {
            "id": event_id,
            "event_type": event_type,
            "source": source,
            "payload": payload,
            "ts": now.isoformat(),
        }

        self._redis_runtime.publish(CHANNEL, json.dumps(event_data, default=str))

        conn = self._get_pg_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO events (id, event_type, source, payload, ts) VALUES (%s, %s, %s, %s, %s)",
                        (event_id, event_type, source, json.dumps(payload, default=str), now),
                    )
            except Exception:
                logger.warning("Failed to persist event to Postgres", exc_info=True)
            finally:
                conn.close()

        logger.info("Event emitted: %s from %s [%s]", event_type, source, event_id)
        return event_id

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_pg_conn()
        if conn is None:
            return []
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, event_type, source, payload, ts FROM events ORDER BY ts DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    entry = dict(row)
                    if isinstance(entry.get("id"), uuid.UUID):
                        entry["id"] = str(entry["id"])
                    if isinstance(entry.get("ts"), datetime):
                        entry["ts"] = entry["ts"].isoformat()
                    if isinstance(entry.get("payload"), str):
                        try:
                            entry["payload"] = json.loads(entry["payload"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(entry)
                return results
        except Exception:
            logger.warning("Failed to fetch recent events", exc_info=True)
            return []
        finally:
            conn.close()

    def get_events_around(self, ts_iso: str, window_seconds: int = 120, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_pg_conn()
        if conn is None:
            return []
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, event_type, source, payload, ts FROM events
                       WHERE ts BETWEEN (%s::timestamptz - interval '%s seconds')
                                    AND (%s::timestamptz + interval '%s seconds')
                       ORDER BY ts ASC LIMIT %s""",
                    (ts_iso, window_seconds, ts_iso, window_seconds, limit),
                )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    entry = dict(row)
                    if isinstance(entry.get("id"), uuid.UUID):
                        entry["id"] = str(entry["id"])
                    if isinstance(entry.get("ts"), datetime):
                        entry["ts"] = entry["ts"].isoformat()
                    if isinstance(entry.get("payload"), str):
                        try:
                            entry["payload"] = json.loads(entry["payload"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(entry)
                return results
        except Exception:
            logger.warning("Failed to fetch events around timestamp", exc_info=True)
            return []
        finally:
            conn.close()
