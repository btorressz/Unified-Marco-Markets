"""Bounded, read-only orchestration for multi-event descriptive research."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.compute.context_governance import governed_decision_context
from backend.compute.decision_outcomes import evaluate_decision_outcomes, symbol_candidates
from backend.compute.event_linked_outcomes import (
    HORIZONS, basis_reactions, event_lag_bucket, funding_reactions, regime_path,
)
from backend.compute.geopolitical_event_study import (
    MAX_REFERENCE_AGE_SECONDS, NEUTRAL_BAND, analyze_symbol,
)
from backend.compute.multi_event_statistics import (
    BOOTSTRAP_ITERATIONS, BOOTSTRAP_METHOD_VERSION, BOOTSTRAP_MIN_N, BOOTSTRAP_SEED,
    MISSING_REASONS, OVERLAP_POLICY_VERSION, STATISTICS_CONTRACT_VERSION,
    WINSORIZATION_POLICY_VERSION, coverage_summary, descriptive_statistics,
    filter_overlaps, sample_hash, transition_matrix,
)
from backend.data.repositories.decision_repo import DecisionRepository
from backend.data.repositories.derivatives_repo import DerivativesRepository
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.data.repositories.research_market_history_repo import (
    INTERVAL_SECONDS, SOURCE_ID, ResearchMarketHistoryRepository,
)

MAX_EVENTS = 250
MAX_STRATA = 25
DECISION_BATCH_SIZE = 250
DECISION_LINK_POLICY_VERSION = "nearest_preceding_event_v1"


def _dt(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _reason(row):
    if row.get("status") == "not_matured":
        return "horizon_not_matured"
    value = str(row.get("reason") or "").lower().replace(" ", "_")
    if "pre-event_reference" in value:
        value = "no_valid_pre_event_reference"
    if "target_tolerance" in value or "within_target" in value:
        value = "no_observation_within_target_tolerance"
    return value if value in MISSING_REASONS else "other_unavailable"


def _contains_exact(value, needles):
    if isinstance(value, dict):
        return any(_contains_exact(item, needles) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact(item, needles) for item in value)
    return str(value) in needles if value is not None else False


class MultiEventReactionService:
    def __init__(self, events=None, history=None, derivatives=None, decisions=None, outcomes=None):
        self.events = events or ResearchEventRepository()
        self.history = history or ResearchMarketHistoryRepository()
        self.derivatives = derivatives or DerivativesRepository()
        self.decisions = decisions or DecisionRepository()
        self.outcomes = outcomes

    @staticmethod
    def _targets(events):
        return [
            {
                "event_id": event["event_id"],
                "event_ts": _dt(event["event_timestamp"]).isoformat(),
                "horizon": horizon,
                "target_ts": (_dt(event["event_timestamp"]) + timedelta(seconds=seconds)).isoformat(),
            }
            for event in events
            for horizon, seconds in HORIZONS.items()
        ]

    @staticmethod
    def _group(rows, timestamp_field):
        grouped = defaultdict(list)
        for row in rows or []:
            item = dict(row)
            if item.get("event_id") and item.get(timestamp_field) is not None:
                grouped[str(item["event_id"])].append(item)
        return grouped

    @staticmethod
    def _query_meta(bundle):
        return {
            "query_mode": bundle.get("query_mode"),
            "truncated": bool(bundle.get("truncated")),
            "requested_target_count": bundle.get("requested_target_count"),
            "max_expected_rows": bundle.get("max_expected_rows"),
            "coverage": bundle.get("coverage") or {},
            "error": bundle.get("error"),
        }

    @staticmethod
    def _price_reasons(analysis, event_ts, rows, coverage):
        event_time = _dt(event_ts)
        first = coverage.get("first_observation_ts")
        first = _dt(first) if first else None
        references = [_dt(row["ts"]) for row in rows or [] if row.get("ts") and _dt(row["ts"]) <= event_time]
        latest_reference = max(references) if references else None
        for result in analysis.values():
            if result.get("status") in {"available", "not_matured"}:
                continue
            if first and event_time < first:
                result["reason"] = "event_predates_dataset"
            elif latest_reference and (event_time - latest_reference).total_seconds() > MAX_REFERENCE_AGE_SECONDS:
                result["reason"] = "reference_stale"
            else:
                result["reason"] = _reason(result)
        return analysis

    def _load_series(self, events, targets, current):
        prices, funding, basis = {}, {}, {}
        query = {"price": {}, "funding": {}, "basis": {}}

        for asset in ("BTC", "ETH", "SOL"):
            symbol = f"{asset}/USD"
            try:
                bundle = self.history.get_event_points_batch(
                    symbol=symbol, interval_seconds=INTERVAL_SECONDS,
                    source_id=SOURCE_ID, event_targets=targets,
                )
            except Exception as exc:
                bundle = {"rows": [], "coverage": {}, "query_mode": "event_target_lateral_v1",
                          "truncated": False, "error": str(exc)}
            grouped = self._group(bundle.get("rows"), "ts")
            prices[asset] = {}
            for event in events:
                event_rows = grouped.get(event["event_id"], [])
                analysis = analyze_symbol(event_rows, event["event_timestamp"], now=current)
                prices[asset][event["event_id"]] = self._price_reasons(
                    analysis, event["event_timestamp"], event_rows, bundle.get("coverage") or {}
                )
            query["price"][asset] = self._query_meta(bundle)

        for asset in ("BTC", "ETH", "SOL"):
            market = f"{asset}-PERP"
            funding_key = f"{market}:hyperliquid"
            try:
                bundle = self.derivatives.get_funding_event_points_batch(
                    venue="hyperliquid", market=market, event_targets=targets
                )
            except Exception as exc:
                bundle = {"rows": [], "coverage": {}, "query_mode": "event_target_lateral_v1",
                          "truncated": False, "error": str(exc)}
            grouped = self._group(bundle.get("rows"), "provider_timestamp")
            funding[funding_key] = {
                event["event_id"]: funding_reactions(
                    grouped.get(event["event_id"], []), event["event_timestamp"],
                    now=current, coverage=bundle.get("coverage") or {},
                )["horizons"]
                for event in events
            }
            query["funding"][funding_key] = self._query_meta(bundle)

            for venue in ("hyperliquid", "drift"):
                key = f"{asset}:{venue}"
                try:
                    b_bundle = self.derivatives.get_basis_event_points_batch(
                        symbol=f"{asset}/USD", venue=venue, market=market, event_targets=targets
                    )
                except Exception as exc:
                    b_bundle = {"rows": [], "coverage": {}, "query_mode": "event_target_lateral_v1",
                                "truncated": False, "error": str(exc)}
                b_grouped = self._group(b_bundle.get("rows"), "observed_at")
                basis[key] = {
                    event["event_id"]: basis_reactions(
                        b_grouped.get(event["event_id"], []), event["event_timestamp"],
                        now=current, coverage=b_bundle.get("coverage") or {},
                    )["horizons"]
                    for event in events
                }
                query["basis"][key] = self._query_meta(b_bundle)
        return prices, funding, basis, query

    def _load_regimes(self, events, earliest, latest, current):
        context = {"regime_snapshots": [], "errors": {}, "truncated": {}}
        if self.outcomes and events:
            try:
                context = self.outcomes.load_context_history(
                    start_ts=earliest - timedelta(hours=6),
                    end_ts=min(current, latest + timedelta(days=7, hours=2)),
                )
            except Exception as exc:
                context["errors"]["context_history"] = str(exc)
        truncated = bool((context.get("truncated") or {}).get("regime_snapshots"))
        if truncated:
            paths = {
                event["event_id"]: {
                    "reference": None,
                    "horizons": {
                        horizon: {"status": "unavailable", "reason": "insufficient_coverage"}
                        for horizon in HORIZONS
                    },
                }
                for event in events
            }
        else:
            paths = {
                event["event_id"]: regime_path(
                    context.get("regime_snapshots") or [], event["event_timestamp"], now=current
                )
                for event in events
            }
        meta = {"truncated": truncated, "source_errors": context.get("errors") or {}}
        return context, paths, meta

    def build(self, *, event_family=None, event_type=None, source_id=None, claim_type=None,
              event_time_basis=None, start_ts=None, end_ts=None, limit=100,
              overlap_policy=OVERLAP_POLICY_VERSION, include_decisions=True, now=None):
        current = _dt(now) if now else datetime.now(timezone.utc)
        limit = max(1, min(int(limit), MAX_EVENTS))
        filters = {
            "event_family": event_family, "event_type": event_type, "source_id": source_id,
            "claim_type": claim_type, "event_time_basis": event_time_basis,
            "start_ts": start_ts, "end_ts": end_ts, "limit": limit,
        }
        kwargs = {key: value for key, value in filters.items() if key != "limit" and value is not None}
        try:
            event_rows = self.events.list_events(
                limit=limit, study_eligible=True, synthetic=False, **kwargs
            )
        except TypeError:
            event_rows = self.events.list_events(
                limit=limit, study_eligible=True,
                **{key: value for key, value in kwargs.items() if key != "event_time_basis"},
            )
        events = [
            {**row, "event_id": str(row.get("id") or row.get("event_id") or row.get("event_key"))}
            for row in event_rows
            if row.get("study_eligible") is True
            and row.get("synthetic") is not True
            and row.get("event_timestamp")
        ]
        events.sort(key=lambda row: (_dt(row["event_timestamp"]), row["event_id"]))
        ids = [row["event_id"] for row in events]
        earliest = min((_dt(event["event_timestamp"]) for event in events), default=current)
        latest = max((_dt(event["event_timestamp"]) for event in events), default=current)
        digest = sample_hash(
            event_ids=ids, filters=filters, horizons=HORIZONS, overlap_policy=overlap_policy
        )

        price_a, funding_a, basis_a, query = self._load_series(
            events, self._targets(events), current
        )
        context, regime_paths, regime_meta = self._load_regimes(
            events, earliest, latest, current
        )
        query["regime"] = regime_meta

        all_stats = self._summary(
            events, price_a, funding_a, basis_a, regime_paths, enforce_time_basis=False
        )
        headline = self._summary(
            events, price_a, funding_a, basis_a, regime_paths, enforce_time_basis=True
        )
        by_basis, basis_meta = self._stratify(
            events, "event_time_basis", price_a, funding_a, basis_a, regime_paths, False
        )
        by_type, type_meta = self._stratify(
            events, "event_type", price_a, funding_a, basis_a, regime_paths, True
        )
        by_family, family_meta = self._stratify(
            events, "event_family", price_a, funding_a, basis_a, regime_paths, True
        )
        decisions = self._decision_statistics(
            events, earliest, latest, current, context, include_decisions
        )
        query["decisions"] = decisions.get("query_integrity") or {}

        basis_counts = self._counts(events, "event_time_basis")
        heterogeneous = len(basis_counts) > 1
        warning = (
            "Headline statistics are suppressed because event_time_basis is heterogeneous. "
            "Use results_by_event_time_basis for like-for-like event-time comparisons."
            if heterogeneous else
            "Many descriptive slices are displayed. Apparent patterns may arise by chance "
            "and require independent validation."
        )
        limitations = [
            "Descriptive associations only; event timing does not establish causality.",
            "Coverage depends on durable locally stored observations.",
            "Overlapping reaction windows are excluded per metric and horizon.",
        ]
        if heterogeneous:
            limitations.append(
                "Combined headline statistics are unavailable for heterogeneous event-time bases."
            )
        if regime_meta["truncated"]:
            limitations.append(
                "Regime history was truncated by its bounded context read; regime statistics "
                "are unavailable rather than treated as complete."
            )
        primary = headline if headline.get("statistics_available") else {}
        return {
            "study": {
                "contract_version": STATISTICS_CONTRACT_VERSION,
                "sample_id": digest[:16], "sample_hash": digest,
                "descriptive_only": True, "causal_claim": False, "research_only": True,
                "persisted": False, "orders_submitted": 0,
            },
            "filters": filters,
            "study_manifest": {
                "study_contract_version": STATISTICS_CONTRACT_VERSION,
                "event_sample_definition": "durable study_eligible non-synthetic research_events",
                "requested_filters": filters,
                "candidate_event_count": len(event_rows),
                "included_event_count": len(events),
                "excluded_event_count": len(event_rows) - len(events),
                "sample_event_ids": ids[:MAX_EVENTS],
                "start_ts": earliest.isoformat() if events else None,
                "end_ts": latest.isoformat() if events else None,
                "evaluated_at": current.isoformat(),
                "horizons": list(HORIZONS), "overlap_policy": overlap_policy,
                "winsorization_policy": WINSORIZATION_POLICY_VERSION,
                "bootstrap_policy": BOOTSTRAP_METHOD_VERSION,
                "coverage_policy": "observed / matured non-overlap eligible",
                "decision_link_policy": DECISION_LINK_POLICY_VERSION,
            },
            "sample": {
                "candidate_event_count": len(event_rows),
                "included_event_count": len(events),
                "excluded_event_count": len(event_rows) - len(events),
                "event_time_basis_counts": basis_counts,
                "event_type_counts": self._counts(events, "event_type"),
                "event_family_counts": self._counts(events, "event_family"),
                "source_counts": self._counts(events, "source_id"),
                "heterogeneous_event_time_basis": heterogeneous,
            },
            "headline_statistics": {
                "available": bool(headline.get("statistics_available")),
                "reason": headline.get("reason"),
            },
            "price_statistics": primary.get("price_statistics", {}),
            "funding_statistics": primary.get("funding_statistics", {}),
            "basis_statistics": primary.get("basis_statistics", {}),
            "regime_statistics": primary.get("regime_statistics", {}),
            "decision_statistics": decisions,
            "results_by_event_time_basis": by_basis,
            "results_by_event_type": by_type,
            "results_by_event_family": by_family,
            "stratification_metadata": {
                "event_time_basis": basis_meta, "event_type": type_meta, "event_family": family_meta
            },
            "missingness": {
                "taxonomy": list(MISSING_REASONS),
                "all_events_by_metric": self._missingness(all_stats),
            },
            "overlap": {"policy": overlap_policy},
            "data_query_integrity": query,
            "statistics_contract": {
                "median_primary": True,
                "bootstrap": {
                    "method": BOOTSTRAP_METHOD_VERSION, "seed": BOOTSTRAP_SEED,
                    "iterations": BOOTSTRAP_ITERATIONS, "minimum_n": BOOTSTRAP_MIN_N,
                },
                "winsorization": {"policy": WINSORIZATION_POLICY_VERSION},
                "sample_quality_thresholds": {
                    "unavailable": 0, "very_low_sample": 5,
                    "low_sample": 20, "moderate_sample": 50,
                },
                "significance_testing": False, "multiple_comparisons": True,
                "warning": warning,
            },
            "limitations": limitations,
        }

    @staticmethod
    def _counts(events, key):
        return dict(sorted(Counter(str(event.get(key) or "UNKNOWN") for event in events).items()))

    @classmethod
    def _summary(cls, events, prices, funding, basis, regimes, enforce_time_basis):
        bases = cls._counts(events, "event_time_basis")
        if enforce_time_basis and len(bases) > 1:
            return {
                "statistics_available": False, "reason": "heterogeneous_event_time_basis",
                "sample_count": len(events), "event_time_basis_counts": bases,
            }
        return {
            "statistics_available": True, "sample_count": len(events), "event_time_basis_counts": bases,
            "price_statistics": {
                key: cls._aggregate(events, value, "observed_return", NEUTRAL_BAND, "price")
                for key, value in prices.items()
            },
            "funding_statistics": {
                key: cls._aggregate(events, value, "delta_bps", 0.0, "funding")
                for key, value in funding.items()
            },
            "basis_statistics": {
                key: cls._aggregate(events, value, "delta_bps", 0.0, "basis")
                for key, value in basis.items()
            },
            "regime_statistics": cls._regimes(events, regimes),
        }

    @classmethod
    def _stratify(cls, events, key, prices, funding, basis, regimes, enforce_time_basis):
        groups = defaultdict(list)
        for event in events:
            groups[str(event.get(key) or "UNKNOWN")].append(event)
        ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
        selected = ordered[:MAX_STRATA]
        return ({
            name: cls._summary(group, prices, funding, basis, regimes, enforce_time_basis)
            for name, group in selected
        }, {
            "group_count": len(groups), "returned_group_count": len(selected),
            "truncated": len(groups) > len(selected), "max_groups": MAX_STRATA,
        })

    @staticmethod
    def _aggregate(events, analyses, value_key, neutral_band, kind):
        output = {}
        for horizon, seconds in HORIZONS.items():
            overlap = filter_overlaps(events, horizon_seconds=seconds)
            allowed = {event["event_id"] for event in overlap["included"]}
            observations = []
            for event in events:
                row = dict((analyses.get(event["event_id"]) or {}).get(horizon) or {})
                if event["event_id"] not in allowed:
                    row = {"status": "unavailable", "reason": "overlap_excluded"}
                elif row.get("status") != "available":
                    row["reason"] = _reason(row)
                observations.append(row)
            coverage = coverage_summary(observations)
            available = [row for row in observations if row.get("status") == "available"]
            stats = descriptive_statistics(
                [row.get(value_key) for row in available], neutral_band=neutral_band
            )
            result = {
                **coverage, "raw_statistics": stats, "median": stats.get("median"),
                "overlap": {key: value for key, value in overlap.items() if key != "included"},
            }
            if kind == "funding":
                directions = Counter(str(row.get("direction") or "UNKNOWN") for row in available)
                flips = sum(row.get("sign_flip") is True for row in available)
                n = len(available)
                result["funding_reaction_counts"] = {
                    "increased_count": directions["INCREASED"],
                    "decreased_count": directions["DECREASED"],
                    "unchanged_count": directions["UNCHANGED"],
                    "sign_flip_count": flips,
                    "increase_rate": directions["INCREASED"] / n if n else None,
                    "decrease_rate": directions["DECREASED"] / n if n else None,
                    "sign_flip_rate": flips / n if n else None,
                }
            elif kind == "basis":
                flips = sum(row.get("sign_flip") is True for row in available)
                down = sum(
                    row.get("reference_sign") == "POSITIVE" and row.get("basis_sign") == "NEGATIVE"
                    for row in available
                )
                up = sum(
                    row.get("reference_sign") == "NEGATIVE" and row.get("basis_sign") == "POSITIVE"
                    for row in available
                )
                result["basis_reaction_counts"] = {
                    "premium_to_discount_count": down,
                    "discount_to_premium_count": up,
                    "sign_flip_count": flips,
                    "sign_flip_rate": flips / len(available) if available else None,
                }
            output[horizon] = result
        return output

    @staticmethod
    def _regimes(events, paths):
        output = {field: {} for field in ("shock_state", "funding_regime", "vol_regime")}
        for field in output:
            for horizon, seconds in HORIZONS.items():
                overlap = filter_overlaps(events, horizon_seconds=seconds)
                allowed = {event["event_id"] for event in overlap["included"]}
                pairs, ref_n, target_n, immature = [], 0, 0, 0
                for event in events:
                    if event["event_id"] not in allowed:
                        continue
                    path = paths.get(event["event_id"]) or {}
                    ref = path.get("reference") or {}
                    target = (path.get("horizons") or {}).get(horizon) or {}
                    if ref.get("status") == "available" and ref.get(field) is not None:
                        ref_n += 1
                    if target.get("status") == "not_matured":
                        immature += 1
                        continue
                    if target.get("status") == "available" and target.get(field) is not None:
                        target_n += 1
                    if ref.get(field) is not None and target.get("status") == "available" and target.get(field) is not None:
                        pairs.append((ref[field], target[field]))
                matrix = transition_matrix(pairs)
                denominator = max(0, len(allowed) - immature)
                observed = matrix["transition_observed_n"]
                output[field][horizon] = {
                    **matrix, "candidate_event_count": len(events),
                    "included_event_count": len(allowed),
                    "overlap_excluded_count": overlap["overlap_excluded_count"],
                    "overlap_excluded_event_ids": overlap["overlap_excluded_event_ids"],
                    "reference_available_n": ref_n, "target_available_n": target_n,
                    "not_matured_n": immature, "missing_n": max(0, denominator - observed),
                    "coverage_denominator_n": denominator,
                    "coverage_rate": observed / denominator if denominator else None,
                }
        return output

    @staticmethod
    def _missingness(summary):
        result = {}
        for metric in ("price_statistics", "funding_statistics", "basis_statistics"):
            counts = Counter()
            for series in (summary.get(metric) or {}).values():
                for horizon in HORIZONS:
                    counts.update((series.get(horizon) or {}).get("missing_reason_counts") or {})
            result[metric] = dict(sorted(counts.items()))
        return result

    @staticmethod
    def _event_ids(event):
        return {
            str(value) for value in (
                event.get("event_id"), event.get("event_key"), event.get("source_record_id")
            ) if value is not None and str(value)
        }

    @classmethod
    def _assign_decision(cls, decision, events):
        decision_ts = _dt(decision.get("decision_ts"))
        eligible = [
            event for event in events
            if _dt(event["event_timestamp"]) <= decision_ts
            and decision_ts - _dt(event["event_timestamp"]) <= timedelta(days=7)
        ]
        if not eligible:
            return None
        provenance = decision.get("input_provenance") or {}
        explicit = [
            event for event in eligible if _contains_exact(provenance, cls._event_ids(event))
        ]
        candidates = explicit or eligible
        event = max(candidates, key=lambda row: (_dt(row["event_timestamp"]), row["event_id"]))
        return event, "explicit_recorded_link" if explicit else "temporal_proximity_only"

    def _decision_statistics(self, events, earliest, latest, current, context, include):
        result = {
            "included": False, "statistics_available": False,
            "candidate_decision_count": 0, "included_decision_count": 0,
            "linked_decision_count": 0, "truncated": False, "query_integrity": {},
            "pnl_semantics": "BLOCK classifications are counterfactual market moves, not realized P&L.",
            "link_policy": DECISION_LINK_POLICY_VERSION,
        }
        if not include or not events:
            return result
        try:
            cohort = self.decisions.list_complete_bounded(
                start_ts=earliest, end_ts=min(current, latest + timedelta(days=7))
            )
        except Exception as exc:
            return {**result, "included": True, "unavailable": True, "reason": str(exc)}
        decisions = list(cohort.get("decisions") or [])
        result.update({
            "included": True,
            "candidate_decision_count": int(cohort.get("candidate_decision_count") or 0),
            "included_decision_count": len(decisions),
            "truncated": bool(cohort.get("truncated")),
            "truncation_reason": cohort.get("truncation_reason"),
            "global_limit": cohort.get("global_limit"),
        })
        if result["truncated"]:
            result["reason"] = "decision_cohort_truncated"
            result["query_integrity"] = {
                "truncated": True, "truncation_reason": result["truncation_reason"],
                "global_limit": result["global_limit"],
            }
            return result
        if not self.outcomes:
            result["reason"] = "decision_outcome_repository_unavailable"
            return result

        linked = []
        for decision in decisions:
            assignment = self._assign_decision(decision, events)
            if assignment:
                event, link_type = assignment
                lag = (_dt(decision["decision_ts"]) - _dt(event["event_timestamp"])).total_seconds()
                linked.append({
                    "decision": decision, "event": event, "link_type": link_type,
                    "event_lag_seconds": lag, "event_lag_bucket": event_lag_bucket(lag),
                })
        result["linked_decision_count"] = len(linked)

        batches, query_count, fallbacks, observations = 0, 0, 0, {}
        for offset in range(0, len(linked), DECISION_BATCH_SIZE):
            chunk = linked[offset:offset + DECISION_BATCH_SIZE]
            batch = self.outcomes.load_horizon_prices_batch(
                requests=[{
                    "request_id": str(item["decision"].get("id")),
                    "decision_ts": item["decision"].get("decision_ts"),
                    "symbols": symbol_candidates(item["decision"]),
                } for item in chunk],
                horizons=HORIZONS,
            )
            observations.update(batch.get("results") or {})
            batches += 1
            query_count += int(batch.get("query_count") or 0)
            fallbacks += int(bool(batch.get("batch_fallback")))

        records = []
        for item in linked:
            decision = item["decision"]
            outcome = evaluate_decision_outcomes(
                decision,
                observations.get(str(decision.get("id"))) or {
                    "available": False, "reason": "batched historical market observations unavailable",
                    "observations": [],
                },
                {"available": False, "reason": "not requested for statistical evaluation"},
            )
            facts = outcome.get("decision") or {}
            governed = governed_decision_context(decision, context)
            records.append({
                **item, "action": str(facts.get("action") or "unknown").upper(),
                "outcomes": outcome.get("outcomes") or {},
                "regime_signature": governed.get("regime_signature", "unavailable"),
            })
        result.update(self._decision_summary(records, subgroups=True))
        result["statistics_available"] = True
        result["query_integrity"] = {
            "truncated": False, "batch_count": batches, "batch_query_count": query_count,
            "batch_fallback_count": fallbacks, "decision_batch_size": DECISION_BATCH_SIZE,
            "context_truncated": dict(context.get("truncated") or {}),
        }
        return result

    @classmethod
    def _decision_summary(cls, records, subgroups=False):
        actions = Counter(row["action"] for row in records)
        result = {
            "decision_count": len(records), "allow_count": actions["ALLOW"],
            "block_count": actions["BLOCK"],
            "link_type_counts": dict(sorted(Counter(row["link_type"] for row in records).items())),
            "event_lag_bucket_counts": dict(sorted(Counter(row["event_lag_bucket"] for row in records).items())),
            "horizons": {},
        }
        for horizon in HORIZONS:
            values = [
                (row.get("outcomes") or {}).get(horizon)
                for row in records
                if isinstance((row.get("outcomes") or {}).get(horizon), dict)
            ]
            result["horizons"][horizon] = {
                "evaluated_n": len(values), "missing_n": len(records) - len(values),
                "classification_counts": dict(sorted(Counter(
                    str(value.get("classification") or "unclassified") for value in values
                ).items())),
            }
        if not subgroups:
            return result

        def grouped(key):
            groups = defaultdict(list)
            for row in records:
                groups[str(key(row) or "UNKNOWN")].append(row)
            return {
                name: cls._decision_summary(items) for name, items in sorted(groups.items())
            }

        result["results_by_link_type"] = grouped(lambda row: row["link_type"])
        result["results_by_regime_signature"] = grouped(lambda row: row["regime_signature"])
        result["results_by_event_type"] = grouped(lambda row: row["event"].get("event_type"))
        result["results_by_event_family"] = grouped(lambda row: row["event"].get("event_family"))
        return result
