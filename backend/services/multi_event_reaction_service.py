"""Bounded, read-only orchestration for multi-event descriptive research."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.compute.event_linked_outcomes import HORIZONS, basis_reactions, funding_reactions, regime_path
from backend.compute.geopolitical_event_study import NEUTRAL_BAND, analyze_symbol
from backend.compute.multi_event_statistics import (
    BOOTSTRAP_ITERATIONS, BOOTSTRAP_METHOD_VERSION, BOOTSTRAP_MIN_N, BOOTSTRAP_SEED,
    MISSING_REASONS, OVERLAP_POLICY_VERSION, STATISTICS_CONTRACT_VERSION,
    WINSORIZATION_POLICY_VERSION, coverage_summary, descriptive_statistics,
    filter_overlaps, sample_hash, transition_matrix,
)
from backend.data.repositories.decision_repo import DecisionRepository
from backend.data.repositories.derivatives_repo import DerivativesRepository
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.data.repositories.research_market_history_repo import INTERVAL_SECONDS, SOURCE_ID, ResearchMarketHistoryRepository

MAX_EVENTS = 250


def _dt(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _reason(row, first=None):
    if row.get("status") == "not_matured": return "horizon_not_matured"
    reason = str(row.get("reason") or "").lower().replace(" ", "_")
    if "pre-event_reference" in reason: reason = "no_valid_pre_event_reference"
    if "target_tolerance" in reason or "within_target" in reason: reason = "no_observation_within_target_tolerance"
    return reason if reason in MISSING_REASONS else "other_unavailable"


class MultiEventReactionService:
    def __init__(self, events=None, history=None, derivatives=None, decisions=None, outcomes=None):
        self.events = events or ResearchEventRepository(); self.history = history or ResearchMarketHistoryRepository()
        self.derivatives = derivatives or DerivativesRepository(); self.decisions = decisions or DecisionRepository()
        self.outcomes = outcomes

    def build(self, *, event_family=None, event_type=None, source_id=None, claim_type=None,
              event_time_basis=None, start_ts=None, end_ts=None, limit=100,
              overlap_policy=OVERLAP_POLICY_VERSION, include_decisions=True, now=None):
        current = _dt(now) if now else datetime.now(timezone.utc); limit = max(1, min(int(limit), MAX_EVENTS))
        filters = {"event_family": event_family, "event_type": event_type, "source_id": source_id,
                   "claim_type": claim_type, "event_time_basis": event_time_basis,
                   "start_ts": start_ts, "end_ts": end_ts, "limit": limit}
        kwargs = {k: v for k, v in filters.items() if k != "limit" and v is not None}
        try: rows = self.events.list_events(limit=limit, study_eligible=True, synthetic=False, **kwargs)
        except TypeError: rows = self.events.list_events(limit=limit, study_eligible=True, **{k:v for k,v in kwargs.items() if k != "event_time_basis"})
        events = [{**row, "event_id": str(row.get("id") or row.get("event_id") or row.get("event_key"))} for row in rows
                  if row.get("study_eligible") is True and row.get("synthetic") is not True and row.get("event_timestamp")]
        events.sort(key=lambda r: (_dt(r["event_timestamp"]), r["event_id"]))
        ids = [r["event_id"] for r in events]
        digest = sample_hash(event_ids=ids, filters=filters, horizons=HORIZONS, overlap_policy=overlap_policy)
        earliest = min((_dt(e["event_timestamp"]) for e in events), default=current)
        latest = max((_dt(e["event_timestamp"]) for e in events), default=current)
        price, funding, basis, regimes = {}, {}, {}, {}
        # One bounded history read per durable price series; no provider fallback.
        for asset in ("BTC", "ETH", "SOL"):
            try: history = self.history.get_history(f"{asset}/USD", INTERVAL_SECONDS, earliest-timedelta(days=1), latest+timedelta(days=7, hours=2), SOURCE_ID, 10000)
            except Exception: history = []
            analyses = {e["event_id"]: analyze_symbol(history, e["event_timestamp"], now=current) for e in events}
            price[asset] = self._aggregate_series(events, analyses, "observed_return", neutral_band=NEUTRAL_BAND)
        # A bounded range read per series, rather than event x horizon queries.
        for asset in ("BTC", "ETH", "SOL"):
            market = f"{asset}-PERP"
            try: rows = self.derivatives.funding_history(venue="hyperliquid", market=market, rate_kind="realized", start_ts=earliest-timedelta(days=1), end_ts=latest+timedelta(days=7, hours=2), limit=1000)
            except Exception: rows = []
            analyses = {e["event_id"]: funding_reactions(rows, e["event_timestamp"], now=current)["horizons"] for e in events}
            funding[f"{market}:hyperliquid"] = self._aggregate_series(events, analyses, "delta_bps")
            for venue in ("hyperliquid", "drift"):
                try: b_rows = self.derivatives.basis_history(symbol=f"{asset}/USD", venue=venue, market=market, start_ts=earliest-timedelta(days=1), end_ts=latest+timedelta(days=7, hours=2), limit=1000)
                except Exception: b_rows = []
                b_analyses = {e["event_id"]: basis_reactions(b_rows, e["event_timestamp"], now=current)["horizons"] for e in events}
                basis[f"{asset}:{venue}"] = self._aggregate_series(events, b_analyses, "delta_bps")
        # Context is loaded once when the injected outcome repository supports it.
        context = {"regime_snapshots": []}
        if self.outcomes:
            try: context = self.outcomes.load_context_history(start_ts=earliest-timedelta(hours=6), end_ts=latest+timedelta(days=7, hours=2))
            except Exception: pass
        for field in ("shock_state", "funding_regime", "vol_regime"):
            regimes[field] = {}
            paths = {e["event_id"]: regime_path(context.get("regime_snapshots", []), e["event_timestamp"], now=current) for e in events}
            for horizon in HORIZONS:
                pairs=[]
                for e in events:
                    path=paths[e["event_id"]]; ref=path.get("reference") or {}; target=path.get("horizons",{}).get(horizon,{})
                    if target.get("status") == "available": pairs.append((ref.get(field), target.get(field)))
                regimes[field][horizon] = transition_matrix(pairs)
        decision_meta = {"included": False, "candidate_decision_count": 0, "included_decision_count": 0, "truncated": False}
        if include_decisions and events:
            try: decision_meta = {"included": True, **self.decisions.list_complete_bounded(start_ts=earliest, end_ts=min(current, latest+timedelta(days=7)))}
            except Exception: decision_meta["unavailable"] = True
            decision_meta.pop("decisions", None)  # bounded response; raw decisions are not a result warehouse
        counts = lambda key: dict(sorted(Counter(str(e.get(key) or "UNKNOWN") for e in events).items()))
        return {"study": {"contract_version": STATISTICS_CONTRACT_VERSION, "sample_id": digest[:16], "sample_hash": digest,
                    "descriptive_only": True, "causal_claim": False, "research_only": True, "persisted": False, "orders_submitted": 0},
                "filters": filters, "study_manifest": {"study_contract_version": STATISTICS_CONTRACT_VERSION,
                    "event_sample_definition": "durable study_eligible non-synthetic research_events", "requested_filters": filters,
                    "candidate_event_count": len(rows), "included_event_count": len(events), "excluded_event_count": len(rows)-len(events),
                    "sample_event_ids": ids[:250], "start_ts": earliest.isoformat() if events else None,
                    "end_ts": latest.isoformat() if events else None, "evaluated_at": current.isoformat(), "horizons": list(HORIZONS),
                    "overlap_policy": overlap_policy, "winsorization_policy": WINSORIZATION_POLICY_VERSION,
                    "bootstrap_policy": BOOTSTRAP_METHOD_VERSION, "coverage_policy": "observed / matured non-overlap eligible"},
                "sample": {"candidate_event_count": len(rows), "included_event_count": len(events), "excluded_event_count": len(rows)-len(events),
                    "event_time_basis_counts": counts("event_time_basis"), "event_type_counts": counts("event_type"),
                    "event_family_counts": counts("event_family"), "source_counts": counts("source_id")},
                "price_statistics": price, "funding_statistics": funding, "basis_statistics": basis,
                "regime_statistics": regimes, "decision_statistics": decision_meta,
                "results_by_event_type": {}, "results_by_event_family": {},
                "missingness": {"taxonomy": list(MISSING_REASONS)}, "overlap": {"policy": overlap_policy},
                "statistics_contract": {"median_primary": True, "bootstrap": {"method": BOOTSTRAP_METHOD_VERSION,
                    "seed": BOOTSTRAP_SEED, "iterations": BOOTSTRAP_ITERATIONS, "minimum_n": BOOTSTRAP_MIN_N},
                    "winsorization": {"policy": WINSORIZATION_POLICY_VERSION},
                    "sample_quality_thresholds": {"unavailable": 0, "very_low_sample": 5, "low_sample": 20, "moderate_sample": 50},
                    "significance_testing": False, "multiple_comparisons": True,
                    "warning": "Many descriptive slices are displayed. Apparent patterns may arise by chance and require independent validation."},
                "limitations": ["Descriptive associations only; event timing does not establish causality.",
                    "Coverage depends on durable locally stored observations.", "Overlapping reaction windows are excluded per metric and horizon."]}

    @staticmethod
    def _aggregate_series(events, analyses, value_key, *, neutral_band=0.0):
        output={}
        for horizon, seconds in HORIZONS.items():
            overlap=filter_overlaps(events, horizon_seconds=seconds); allowed={e["event_id"] for e in overlap["included"]}
            observations=[]
            for event in events:
                row=dict((analyses.get(event["event_id"]) or {}).get(horizon) or {})
                if event["event_id"] not in allowed: row={"status":"unavailable","reason":"overlap_excluded"}
                elif row.get("status") != "available": row["reason"]=_reason(row)
                observations.append(row)
            coverage=coverage_summary(observations); values=[r.get(value_key) for r in observations if r.get("status") == "available"]
            output[horizon]={**coverage, "raw_statistics": descriptive_statistics(values, neutral_band=neutral_band),
                "median": descriptive_statistics(values, neutral_band=neutral_band).get("median"),
                "overlap": {k:v for k,v in overlap.items() if k != "included"}}
        return output
