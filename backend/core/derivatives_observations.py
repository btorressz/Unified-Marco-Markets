"""Versioned, provider-truthful derivatives observation contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60
FUNDING_CONTRACT_VERSION = 1
DERIVATIVES_MARKETS = ("BTC-PERP", "ETH-PERP", "SOL-PERP")


def annualize_rate(rate_per_interval: float, interval_seconds: int) -> float:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    return float(rate_per_interval) * SECONDS_PER_YEAR / interval_seconds


class FundingObservation(BaseModel):
    contract_version: int = FUNDING_CONTRACT_VERSION
    source_id: str
    venue: str
    market: str
    rate_kind: str
    raw_funding_rate: float | None = None
    normalized_funding_rate: float | None = None
    interval_seconds: int | None = None
    long_cashflow_rate: float | None = None
    short_cashflow_rate: float | None = None
    annualized_rate: float | None = None
    provider_timestamp: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timestamp_semantics: str
    sign_convention: str | None = None
    research_only: bool = True
    execution_eligible: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.market not in DERIVATIVES_MARKETS:
            raise ValueError("unsupported derivatives market")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.execution_eligible and self.research_only:
            raise ValueError("research-only observations cannot be execution eligible")
        return self

    @classmethod
    def symmetric(
        cls, *, source_id: str, venue: str, market: str, rate_kind: str,
        raw_rate: float, normalized_rate: float, interval_seconds: int,
        provider_timestamp: datetime | None, timestamp_semantics: str,
        metadata: dict[str, Any] | None = None,
    ) -> "FundingObservation":
        return cls(
            source_id=source_id, venue=venue, market=market, rate_kind=rate_kind,
            raw_funding_rate=raw_rate, normalized_funding_rate=normalized_rate,
            interval_seconds=interval_seconds,
            long_cashflow_rate=-normalized_rate, short_cashflow_rate=normalized_rate,
            annualized_rate=annualize_rate(normalized_rate, interval_seconds),
            provider_timestamp=provider_timestamp,
            timestamp_semantics=timestamp_semantics,
            sign_convention="positive_normalized_rate_means_longs_pay_shorts",
            metadata=metadata or {},
        )

    @classmethod
    def asymmetric(
        cls, *, source_id: str, venue: str, market: str, rate_kind: str,
        raw_long_rate: float, raw_short_rate: float,
        long_cashflow_rate: float, short_cashflow_rate: float,
        interval_seconds: int, provider_timestamp: datetime | None,
        timestamp_semantics: str, sign_convention: str,
        metadata: dict[str, Any] | None = None,
    ) -> "FundingObservation":
        """Build a side-specific observation without inventing a scalar rate.

        ``annualized_rate`` and ``normalized_funding_rate`` intentionally remain
        null: neither side is a faithful compatibility scalar when caps make the
        cashflows asymmetric.  Annualized side values are retained in metadata.
        """
        return cls(
            source_id=source_id, venue=venue, market=market, rate_kind=rate_kind,
            interval_seconds=interval_seconds,
            long_cashflow_rate=long_cashflow_rate,
            short_cashflow_rate=short_cashflow_rate,
            provider_timestamp=provider_timestamp,
            timestamp_semantics=timestamp_semantics,
            sign_convention=sign_convention,
            metadata={
                **(metadata or {}),
                "raw_long_rate": raw_long_rate,
                "raw_short_rate": raw_short_rate,
                "annualized_long_cashflow": annualize_rate(long_cashflow_rate, interval_seconds),
                "annualized_short_cashflow": annualize_rate(short_cashflow_rate, interval_seconds),
                "compatibility_scalar": None,
            },
        )


def unavailable_funding(reason: str, **metadata: Any) -> dict[str, Any]:
    return {"available": False, "reason": reason, "metadata": metadata}
