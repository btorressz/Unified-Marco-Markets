from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class IndexLatestResponse(BaseModel):
    tariff_index: float
    shock_score: float
    ts: datetime
    components: dict[str, float] = Field(default_factory=dict)


class IndexHistoryResponse(BaseModel):
    points: list[dict[str, Any]] = Field(default_factory=list)
    window: str = "24h"
    count: int = 0


class IndexComponentsResponse(BaseModel):
    wits_weight: float = 0.0
    gdelt_weight: float = 0.0
    funding_weight: float = 0.0
    components: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketDataResponse(BaseModel):
    symbol: str
    price: float
    source: str
    confidence: float = 1.0
    funding_rate: float | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DivergenceResponse(BaseModel):
    market: str
    venue_a: str
    venue_b: str
    price_a: float
    price_b: float
    spread_bps: float
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertResponse(BaseModel):
    alert_type: str
    message: str
    severity: str = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RuleActionResponse(BaseModel):
    rule_name: str
    rule_id: str | None = None
    rule_version: int | None = None
    evaluation_type: str | None = None
    expected_direction: str | None = None
    action_type: str
    venue: str
    market: str
    side: str
    size: float
    reason: str = ""
    approved: bool = False
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionStatusResponse(BaseModel):
    order_id: str
    venue: str
    market: str
    status: str
    filled_size: float = 0.0
    avg_price: float | None = None
    error: str | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskStatusResponse(BaseModel):
    throttle_active: bool = False
    throttle_reason: str = ""
    current_leverage: float = 0.0
    margin_usage: float = 0.0
    daily_pnl: float = 0.0
    max_leverage: float = 3.0
    max_margin_usage: float = 0.6
    max_daily_loss: float = 500.0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PortfolioSnapshot(BaseModel):
    cash: float = 0.0
    collateral: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0
    maintenance_margin: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    open_order_exposure: float = 0.0
    available_buying_power: float = 0.0
    asset_exposure: dict[str, float] = Field(default_factory=dict)
    venue_exposure: dict[str, float] = Field(default_factory=dict)
    strategy_exposure: dict[str, float] = Field(default_factory=dict)

    @property
    def equity(self) -> float:
        return self.cash + self.collateral + self.realized_pnl + self.unrealized_pnl


class StressTestResult(BaseModel):
    scenario: str
    price_shock_pct: float
    projected_pnl: float
    projected_margin: float
    would_liquidate: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class EventResponse(BaseModel):
    id: str
    event_type: str
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    database: bool = False
    redis: bool = False
    uptime_seconds: float = 0.0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
