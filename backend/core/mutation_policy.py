"""Central classification policy for state-capable HTTP routes.

Every POST/PUT/PATCH/DELETE API route must be classified here. The registry is
intentionally explicit so the application can fail startup/tests when a new
mutation surface is added without an authorization decision.

This is not an identity or RBAC system. It distinguishes operator-controlled
state mutations from bounded calculation/research requests that happen to use
mutating HTTP verbs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from starlette.routing import compile_path

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class MutationClass(str, Enum):
    EXTERNAL_STATE_MUTATION = "external_state_mutation"
    CALCULATION_ONLY = "calculation_only"


@dataclass(frozen=True)
class MutationPolicy:
    method: str
    path: str
    classification: MutationClass
    reason: str


def _policy(method: str, path: str, classification: MutationClass, reason: str) -> MutationPolicy:
    return MutationPolicy(method.upper(), path.rstrip("/") or "/", classification, reason)


# Preserve the existing protected surface while making every calculation POST
# explicit as well. Route-template strings match FastAPI's registered paths.
MUTATION_POLICIES: tuple[MutationPolicy, ...] = (
    # Execution / durable operator mutations.
    _policy("POST", "/api/execution/order", MutationClass.EXTERNAL_STATE_MUTATION, "submits or records an execution order"),
    _policy("POST", "/api/execution/conditional-order", MutationClass.EXTERNAL_STATE_MUTATION, "creates a durable conditional order"),
    _policy("POST", "/api/execution/conditional-orders/evaluate", MutationClass.EXTERNAL_STATE_MUTATION, "may trigger governed conditional execution"),
    _policy("DELETE", "/api/execution/conditional-order/{order_id}", MutationClass.EXTERNAL_STATE_MUTATION, "cancels a durable conditional order"),
    _policy("POST", "/api/execution/smart-order", MutationClass.EXTERNAL_STATE_MUTATION, "creates a smart execution schedule"),
    _policy("POST", "/api/execution/jupiter/swap", MutationClass.EXTERNAL_STATE_MUTATION, "direct external swap path with an independent feature gate"),

    # Model / research artifacts that durably change governed state.
    _policy("POST", "/api/ml/train/offline", MutationClass.EXTERNAL_STATE_MUTATION, "creates durable governed training/model artifacts"),
    _policy("POST", "/api/ml/models/{model_id}/promote", MutationClass.EXTERNAL_STATE_MUTATION, "changes the active governed model"),
    _policy("POST", "/api/ml/models/{model_id}/rollback", MutationClass.EXTERNAL_STATE_MUTATION, "changes the active governed model"),
    _policy("POST", "/api/decisions", MutationClass.EXTERNAL_STATE_MUTATION, "appends to the durable immutable decision audit ledger"),
    _policy("POST", "/api/heuristics/evaluate", MutationClass.EXTERNAL_STATE_MUTATION, "persists historical heuristic evaluations by default"),
    _policy("POST", "/api/backtest/run", MutationClass.EXTERNAL_STATE_MUTATION, "creates and completes durable backtest run records"),
    _policy("POST", "/api/watchlists", MutationClass.EXTERNAL_STATE_MUTATION, "creates user watchlist state"),
    _policy("PUT", "/api/watchlists/{watchlist_id}", MutationClass.EXTERNAL_STATE_MUTATION, "updates user watchlist state"),
    _policy("DELETE", "/api/watchlists/{watchlist_id}", MutationClass.EXTERNAL_STATE_MUTATION, "deletes user watchlist state"),

    # Calculation/research-only POSTs. These may update transient caches or emit
    # research events, but they do not perform the governed external/durable
    # mutations protected above and intentionally remain usable without operator
    # authorization solely because they use POST.
    _policy("POST", "/api/execution/jupiter/quote", MutationClass.CALCULATION_ONLY, "read-only quote calculation; no swap submitted"),
    _policy("POST", "/api/risk/stress-test", MutationClass.CALCULATION_ONLY, "bounded stress calculation"),
    _policy("POST", "/api/risk/montecarlo/run", MutationClass.CALCULATION_ONLY, "bounded Monte Carlo calculation"),
    _policy("POST", "/api/allocation/rebalance-preview", MutationClass.CALCULATION_ONLY, "proposal-only rebalance preview"),
    _policy("POST", "/api/allocation/execution-preview", MutationClass.CALCULATION_ONLY, "proposal-only execution preview"),
    _policy("POST", "/api/scenario/run", MutationClass.CALCULATION_ONLY, "scenario calculation"),
    _policy("POST", "/api/geopolitical/scenario-run", MutationClass.CALCULATION_ONLY, "geopolitical scenario calculation; no orders submitted"),
    _policy("POST", "/api/protection/preview", MutationClass.CALCULATION_ONLY, "portfolio-protection preview"),
    _policy("POST", "/api/hedge/preview", MutationClass.CALCULATION_ONLY, "cross-asset hedge preview"),
    _policy("POST", "/api/slippage/estimate", MutationClass.CALCULATION_ONLY, "slippage estimate"),
    _policy("POST", "/api/replay/run", MutationClass.CALCULATION_ONLY, "research replay calculation"),
    _policy("POST", "/api/replay/trade-simulation", MutationClass.CALCULATION_ONLY, "simulation only; no real trade"),
    _policy("POST", "/api/sandbox/run", MutationClass.CALCULATION_ONLY, "strategy sandbox comparison"),
    _policy("POST", "/api/decisions/{decision_id}/replay", MutationClass.CALCULATION_ONLY, "immutable decision replay"),
    _policy("POST", "/api/decisions/{decision_id}/counterfactual", MutationClass.CALCULATION_ONLY, "research-only counterfactual replay"),
    _policy("POST", "/api/decisions/{decision_id}/sensitivity", MutationClass.CALCULATION_ONLY, "research-only bounded sensitivity calculation"),
)


_POLICY_BY_ROUTE: dict[tuple[str, str], MutationPolicy] = {}
for _entry in MUTATION_POLICIES:
    _key = (_entry.method, _entry.path)
    if _key in _POLICY_BY_ROUTE:
        raise RuntimeError(f"Duplicate mutation policy: {_entry.method} {_entry.path}")
    _POLICY_BY_ROUTE[_key] = _entry

_COMPILED_POLICIES = tuple(
    (entry, compile_path(entry.path)[0]) for entry in MUTATION_POLICIES
)


def _normalize_path(path: str) -> str:
    value = str(path or "")
    if value != "/":
        value = value.rstrip("/")
    return value or "/"


def is_mutating_method(method: str) -> bool:
    return str(method or "").upper() in MUTATING_METHODS


def get_mutation_policy(method: str, path: str) -> MutationPolicy | None:
    """Resolve a concrete request path to its explicit policy."""
    normalized_method = str(method or "").upper()
    if normalized_method not in MUTATING_METHODS:
        return None
    normalized_path = _normalize_path(path)
    for entry, pattern in _COMPILED_POLICIES:
        if entry.method == normalized_method and pattern.match(normalized_path):
            return entry
    return None


def get_route_template_policy(method: str, route_path: str) -> MutationPolicy | None:
    """Resolve an already-templated FastAPI route path exactly."""
    return _POLICY_BY_ROUTE.get((str(method or "").upper(), _normalize_path(route_path)))


def classify_mutation(method: str, path: str) -> MutationClass | None:
    policy = get_mutation_policy(method, path)
    return policy.classification if policy else None


def is_external_state_mutation(method: str, path: str) -> bool:
    return classify_mutation(method, path) == MutationClass.EXTERNAL_STATE_MUTATION


def mutation_route_inventory(app: Any) -> dict[str, Any]:
    """Compare the live FastAPI mutation surface with the declared registry."""
    classified: list[dict[str, str]] = []
    unclassified: list[dict[str, str]] = []
    actual_keys: set[tuple[str, str]] = set()

    for route in getattr(app, "routes", ()):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or ()
        if not path:
            continue
        normalized_path = _normalize_path(path)
        for method in sorted({str(item).upper() for item in methods} & MUTATING_METHODS):
            key = (method, normalized_path)
            actual_keys.add(key)
            policy = _POLICY_BY_ROUTE.get(key)
            row = {"method": method, "path": normalized_path}
            if policy is None:
                unclassified.append(row)
            else:
                classified.append({
                    **row,
                    "classification": policy.classification.value,
                    "reason": policy.reason,
                })

    stale = [
        {
            "method": policy.method,
            "path": policy.path,
            "classification": policy.classification.value,
        }
        for policy in MUTATION_POLICIES
        if (policy.method, policy.path) not in actual_keys
    ]
    external_count = sum(
        row.get("classification") == MutationClass.EXTERNAL_STATE_MUTATION.value
        for row in classified
    )
    calculation_count = sum(
        row.get("classification") == MutationClass.CALCULATION_ONLY.value
        for row in classified
    )
    return {
        "mutation_route_count": len(actual_keys),
        "policy_count": len(MUTATION_POLICIES),
        "classified_count": len(classified),
        "external_state_mutation_count": external_count,
        "calculation_only_count": calculation_count,
        "classified": classified,
        "unclassified": unclassified,
        "stale_registry_entries": stale,
        "complete": not unclassified and not stale and len(actual_keys) == len(MUTATION_POLICIES),
    }


def validate_mutation_route_inventory(
    app: Any,
    *,
    require_all_policies: bool = True,
) -> dict[str, Any]:
    """Fail closed when an application mutation is missing an explicit policy."""
    report = mutation_route_inventory(app)
    errors: list[str] = []
    if report["unclassified"]:
        errors.append(
            "unclassified="
            + ", ".join(f"{row['method']} {row['path']}" for row in report["unclassified"])
        )
    if require_all_policies and report["stale_registry_entries"]:
        errors.append(
            "stale_registry="
            + ", ".join(
                f"{row['method']} {row['path']}" for row in report["stale_registry_entries"]
            )
        )
    if errors:
        raise RuntimeError("Mutation authorization inventory is incomplete: " + "; ".join(errors))
    return report
