import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PriceTick(BaseModel):
    symbol: str
    venue: str
    price: float
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0


class FundingTick(BaseModel):
    venue: str
    market: str
    funding_rate: float
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    contract_version: int = 0


class OrderbookSnap(BaseModel):
    venue: str
    market: str
    bids: list[list[float]] = Field(default_factory=list)
    asks: list[list[float]] = Field(default_factory=list)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IndexTick(BaseModel):
    tariff_index: float
    shock_score: float = 0.0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PositionState(BaseModel):
    venue: str
    market: str
    size: float
    entry_price: float
    pnl: float = 0.0
    margin: float = 0.0
    liq_price: float | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Event(BaseModel):
    event_type: str
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class TradeAction(BaseModel):
    action_type: str
    venue: str
    market: str
    side: str
    size: float
    reason: str = ""
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
