"""Compatibility import for the shared observation-quality contract."""
from backend.core.observation_quality import (
    OBSERVATION_CONTRACT_VERSION,
    age_seconds,
    is_observed_snapshot,
    observation_quality,
)

__all__ = [
    "OBSERVATION_CONTRACT_VERSION",
    "age_seconds",
    "is_observed_snapshot",
    "observation_quality",
]
