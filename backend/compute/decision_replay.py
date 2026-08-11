"""Canonical decision hashing and read-only historical replay.

This module deliberately imports no execution package, StateStore, or Redis code.
Replay validates the recorded component identities and reconstructs only from the
immutable audit snapshot; it can never route or persist an order.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable


HASH_FIELDS = (
    "decision_ts", "input_state", "input_provenance", "derived_state",
    "heuristic_result", "ml_result", "risk_result", "allocation_result",
    "execution_intent", "component_versions", "config_snapshot", "final_decision",
)


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_decision_state(record: dict[str, Any]) -> dict[str, Any]:
    return {field: _normalize(record.get(field, {} if field != "decision_ts" else None)) for field in HASH_FIELDS}


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decision_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(canonical_decision_state(record)).encode("utf-8")).hexdigest()


compute_decision_hash = decision_hash


def structured_diff(original: Any, replayed: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(original, dict) and isinstance(replayed, dict):
        result = []
        for key in sorted(set(original) | set(replayed)):
            child = f"{path}.{key}" if path else str(key)
            if key not in original:
                result.append({"path": child, "original": None, "replay": replayed[key]})
            elif key not in replayed:
                result.append({"path": child, "original": original[key], "replay": None})
            else:
                result.extend(structured_diff(original[key], replayed[key], child))
        return result
    if isinstance(original, list) and isinstance(replayed, list):
        result = []
        for index in range(max(len(original), len(replayed))):
            child = f"{path}[{index}]"
            if index >= len(original): result.append({"path": child, "original": None, "replay": replayed[index]})
            elif index >= len(replayed): result.append({"path": child, "original": original[index], "replay": None})
            else: result.extend(structured_diff(original[index], replayed[index], child))
        return result
    return [] if _normalize(original) == _normalize(replayed) else [{"path": path, "original": original, "replay": replayed}]


def _unavailable(reason: str, record: dict[str, Any]) -> dict[str, Any]:
    return {"replay_status": "unavailable", "status": "UNAVAILABLE", "reason": reason,
            "original_decision": canonical_decision_state(record), "replayed_decision": None,
            "original_hash": record.get("decision_hash") or decision_hash(record), "replay_hash": None,
            "exact_match": False, "differences": [], "audit_only": True, "orders_submitted": 0}


def replay_decision(record: dict[str, Any], *, model_loader: Callable[[str], Any] | None = None,
                    heuristic_versions: set[str] | None = None,
                    replay_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Reconstruct a decision using only its stored snapshot and exact identities."""
    if replay_builder is None:
        try:
            from backend.compute.decision_evaluator import recompute_decision
            rebuilt = recompute_decision(record, model_loader=model_loader)
        except Exception as exc:
            return _unavailable(str(exc), record)
    else:
        rebuilt = replay_builder(dict(record))
    versions = record.get("component_versions") or {}
    heuristic = versions.get("heuristic") or versions.get("heuristics")
    requested = []
    if isinstance(heuristic, str): requested = [heuristic]
    elif isinstance(heuristic, list): requested = [str(item) for item in heuristic]
    elif isinstance(heuristic, dict):
        requested = [f"{key}:v{value}" if not str(value).startswith("v") else f"{key}:{value}" for key, value in heuristic.items()]
    if heuristic_versions is not None:
        missing = [item for item in requested if item not in heuristic_versions]
        if missing: return _unavailable(f"required heuristic version unavailable: {', '.join(missing)}", record)

    ml = ((record.get("input_state") or {}).get("replay_inputs") or {}).get("ml") or {}
    model_id = ml.get("model_id") or versions.get("model_id")
    if model_id and not ml.get("fallback_used", False):
        if model_loader is None:
            from backend.data.repositories.ml_repo import MLRepository
            model_loader = MLRepository().get_model
        try: model = model_loader(str(model_id))
        except Exception as exc: return _unavailable(f"required ML artifact unavailable: {exc}", record)
        if not model: return _unavailable(f"required ML model unavailable: {model_id}", record)
        expected_sha = ml.get("artifact_sha256") or versions.get("artifact_sha256")
        if expected_sha and model.get("artifact_sha256") != expected_sha:
            return _unavailable("required ML artifact SHA-256 does not match", record)

    original = canonical_decision_state(record)
    replayed = canonical_decision_state(rebuilt)
    original_hash = record.get("decision_hash") or decision_hash(record)
    replay_hash = hashlib.sha256(canonical_json(replayed).encode("utf-8")).hexdigest()
    differences = structured_diff(original, replayed)
    exact = original_hash == replay_hash and not differences
    return {"replay_status": "exact_match" if exact else "mismatch", "status": "EXACT MATCH" if exact else "MISMATCH",
            "original_decision": original, "replayed_decision": replayed, "original_hash": original_hash,
            "replay_hash": replay_hash, "exact_match": exact, "differences": differences,
            "audit_only": True, "orders_submitted": 0}


DecisionReplay = replay_decision
