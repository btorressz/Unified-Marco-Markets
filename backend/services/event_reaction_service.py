"""Read-only orchestration for the bounded single-event Reaction Lab v2."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.compute.context_governance import governed_decision_context
from backend.compute.decision_outcomes import HORIZONS, evaluate_decision_outcomes, symbol_candidates
from backend.compute.event_linked_outcomes import basis_reactions, event_lag_bucket, funding_reactions, regime_path
from backend.data.repositories.decision_outcome_repo import DecisionOutcomeRepository
from backend.data.repositories.decision_repo import DecisionRepository
from backend.data.repositories.derivatives_repo import DerivativesRepository

MAX_DECISIONS = 50


def _dt(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _contains_exact(value, event_id):
    if isinstance(value, dict): return any(_contains_exact(v, event_id) for v in value.values())
    if isinstance(value, list): return any(_contains_exact(v, event_id) for v in value)
    return str(value) == str(event_id)


class EventReactionService:
    def __init__(self, derivatives=None, decisions=None, outcomes=None):
        self.derivatives = derivatives or DerivativesRepository()
        self.decisions = decisions or DecisionRepository()
        self.outcomes = outcomes or DecisionOutcomeRepository()

    def build(self, event, *, now=None):
        event_ts = _dt(event["event_timestamp"]); current = _dt(now) if now else datetime.now(timezone.utc)
        targets = [event_ts + timedelta(seconds=s) for s in HORIZONS.values()]
        funding, basis = {}, {}
        for base in ("BTC", "ETH", "SOL"):
            market = f"{base}-PERP"
            try: rows = self.derivatives.get_funding_event_points(venue="hyperliquid", market=market, event_ts=event_ts, horizon_targets=targets)
            except Exception: rows = []
            funding[market] = funding_reactions(rows, event_ts, now=current)
            for venue in ("hyperliquid", "drift"):
                try: rows = self.derivatives.get_basis_event_points(symbol=f"{base}/USD", venue=venue, market=market, event_ts=event_ts, horizon_targets=targets)
                except Exception: rows = []
                basis[f"{base}:{venue}"] = basis_reactions(rows, event_ts, now=current)
        try: funding_coverage = self.derivatives.funding_coverage(rate_kind="realized")
        except Exception: funding_coverage = []
        try: basis_coverage = self.derivatives.basis_coverage()
        except Exception: basis_coverage = []

        end = min(event_ts + timedelta(days=7), current)
        try: decisions = self.decisions.list(decision_type="execution_pre_trade_final", start_ts=event_ts, end_ts=end, limit=MAX_DECISIONS)
        except Exception: decisions = []
        try: context = self.outcomes.load_context_history(start_ts=event_ts-timedelta(hours=6), end_ts=end)
        except Exception: context = {"regime_snapshots": []}
        requests = [{"decision_id": str(d.get("id")), "decision_ts": d.get("decision_ts"), "symbols": symbol_candidates(d)} for d in decisions]
        batch = self.outcomes.load_horizon_prices_batch(requests=requests, horizons=HORIZONS) if requests else {"results": {}, "query_count": 0}
        rendered, buckets = [], {k: 0 for k in ("0_to_1h", "1h_to_4h", "4h_to_24h", "24h_to_7d")}
        for decision in decisions:
            lag = (_dt(decision["decision_ts"]) - event_ts).total_seconds(); bucket = event_lag_bucket(lag); buckets[bucket] += 1
            explicit = _contains_exact(decision.get("input_provenance") or {}, event.get("event_id"))
            outcome = evaluate_decision_outcomes(decision, (batch.get("results") or {}).get(str(decision.get("id")), {"available": False}))
            facts = outcome.get("decision") or {}
            rendered.append({"decision_id": str(decision.get("id")), "decision_ts": _dt(decision["decision_ts"]).isoformat(),
                "event_lag_seconds": lag, "event_lag_bucket": bucket, "venue": decision.get("venue"), "market": decision.get("market"),
                "symbol": decision.get("symbol"), "side": facts.get("side"), "decision": str(facts.get("action") or "unknown").upper(),
                "link_type": "explicit_recorded_link" if explicit else "temporal_proximity_only",
                "context": governed_decision_context(decision, context), "component_versions": decision.get("component_versions") or {},
                "outcome_status": outcome.get("outcome_status"), "outcomes": outcome.get("outcomes"), "interpretation": outcome.get("interpretation")})
        summary = {"decision_count": len(rendered), "allow_count": sum(d["decision"] == "ALLOW" for d in rendered),
                   "block_count": sum(d["decision"] == "BLOCK" for d in rendered)}
        summary["evaluated_by_horizon"] = {h: sum((d.get("outcomes") or {}).get(h) is not None for d in rendered) for h in HORIZONS}
        summary["missing_by_horizon"] = {h: len(rendered)-summary["evaluated_by_horizon"][h] for h in HORIZONS}
        return {"derivatives_reactions": {"contract_version": 1, "funding": funding, "basis": basis,
                    "coverage": {"funding": funding_coverage, "basis": basis_coverage, "drift_funding": {"status": "unavailable", "reason": "contract_unverified"}}},
                "regime_outcomes": regime_path(context.get("regime_snapshots") or [], event_ts, now=current),
                "decision_outcomes": {"link_semantics": "temporal_proximity_only", "decision_count": len(rendered), "max_decisions": MAX_DECISIONS,
                    "lag_buckets": buckets, "summary": summary, "decisions": rendered,
                    "coverage": {"window_end": end.isoformat(), "batch_query_count": batch.get("query_count", 0), "read_only": True}},
                "research_contract": {"single_event": True, "descriptive_only": True, "causal_claim": False,
                    "research_only": True, "execution_eligible": False, "orders_submitted": 0}}
