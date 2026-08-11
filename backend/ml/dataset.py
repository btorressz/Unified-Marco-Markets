"""Immutable definitions and deterministic governed dataset manifests."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from backend.ml.feature_store import FEATURE_NAMES, FEATURE_SCHEMA_ID, FEATURE_SCHEMA_VERSION, features_to_vector

LABEL_DEFINITION_ID = "forward_direction"
LABEL_DEFINITION_VERSION = 1
LABEL_HORIZON = "24h"
label_definition_id = LABEL_DEFINITION_ID
label_definition_version = LABEL_DEFINITION_VERSION
LABEL_DEFINITION = {"label_definition_id": LABEL_DEFINITION_ID, "label_definition_version": LABEL_DEFINITION_VERSION,
                    "horizon": LABEL_HORIZON, "positive": "future_return > 0", "negative": "future_return < 0",
                    "neutral": "excluded"}

def _timestamp(sample: dict[str, Any]) -> str:
    value = sample.get("timestamp", sample.get("ts"))
    if value is None: raise ValueError("Every governed observation requires a timestamp")
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def create_dataset_manifest(samples: list[dict[str, Any]], labels: list[int], **metadata) -> dict[str, Any]:
    if len(samples) != len(labels) or not samples: raise ValueError("samples and labels must be non-empty and equal length")
    timestamps = [_timestamp(row) for row in samples]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Governed observations must have unique, strictly ordered timestamps")
    vectors = [features_to_vector(row.get("features", row)) for row in samples]
    canonical = {"timestamps": timestamps, "feature_vectors": vectors, "labels": [int(x) for x in labels],
                 "feature_schema_id": FEATURE_SCHEMA_ID, "feature_schema_version": FEATURE_SCHEMA_VERSION,
                 "label_definition_id": LABEL_DEFINITION_ID, "label_definition_version": LABEL_DEFINITION_VERSION}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    provenance = [row.get("feature_provenance", {}) for row in samples]
    status_count = lambda status: sum(p.get("status") == status for item in provenance for p in item.values())
    return {"dataset_id": f"ds_{digest[:16]}", "dataset_hash": digest, "feature_schema_id": FEATURE_SCHEMA_ID,
            "feature_schema_version": FEATURE_SCHEMA_VERSION, **LABEL_DEFINITION, "observation_start": timestamps[0],
            "observation_end": timestamps[-1], "sample_count": len(labels), "positive_count": sum(int(x)==1 for x in labels),
            "negative_count": sum(int(x)==0 for x in labels), "venue": metadata.get("venue"), "market": metadata.get("market"),
            "symbol": metadata.get("symbol"), "source_ids": sorted(set(metadata.get("source_ids") or [])),
            "ingest_run_ids": sorted(set(metadata.get("ingest_run_ids") or [])),
            "provenance_ids": sorted(set(metadata.get("provenance_ids") or [])),
            "default_feature_count": status_count("default"), "fallback_feature_count": status_count("fallback")}
