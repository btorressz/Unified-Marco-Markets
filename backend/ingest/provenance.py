"""Small mutable fact collector passed through an ingestion attempt."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def sanitize_error(value: object, limit: int = 1500) -> str:
    text = str(value).replace("\x00", "")
    return text[:limit]


@dataclass
class IngestRunContext:
    source_id: str
    run_id: str | None = None
    records_received: int = 0
    records_persisted: int = 0
    provider_timestamp: datetime | None = None
    received_at: datetime | None = None
    provider_success: bool | None = None
    fallback_used: bool = False
    fallback_source_id: str | None = None
    fallback_type: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_received(self, count: int = 1) -> None:
        self.records_received += max(0, int(count)); self.received_at = self.received_at or datetime.now(timezone.utc)

    def record_persisted(self, count: int = 1) -> None:
        self.records_persisted += max(0, int(count))

    def set_provider_timestamp(self, ts: datetime | None) -> None:
        self.provider_timestamp = ts

    def mark_success(self) -> None:
        self.provider_success = True

    def mark_fallback(self, source_id: str | None = None, fallback_type: str | None = None, reason: str | None = None) -> None:
        self.provider_success = False; self.fallback_used = True
        self.fallback_source_id = source_id; self.fallback_type = fallback_type
        if reason: self.metadata["fallback_reason"] = reason

    def mark_failure(self, error: object) -> None:
        self.provider_success = False; self.error_type = type(error).__name__; self.error_message = sanitize_error(error)

    @property
    def status(self) -> str:
        if self.fallback_used: return "fallback"
        if self.provider_success is False: return "failure"
        if self.provider_success is True and self.metadata.get("partial_provider_failure"): return "partial"
        if self.provider_success is True and self.records_received and not self.records_persisted: return "partial"
        return "success" if self.provider_success is True else "failure"

    def finish_fields(self) -> dict[str, Any]:
        return {"status": self.status, "records_received": self.records_received, "records_persisted": self.records_persisted, "fallback_used": self.fallback_used, "fallback_source_id": self.fallback_source_id, "fallback_type": self.fallback_type, "provider_timestamp": self.provider_timestamp, "error_type": self.error_type, "error_message": self.error_message, "metadata": self.metadata}
