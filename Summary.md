# Tariff Risk Desk — Full Summary

## What Is This?

The Tariff Risk Desk is a real-time macro-to-markets research and risk-management dashboard that watches global trade policy, geopolitical events, market structure, stablecoins, equities, and crypto markets and connects those signals to deterministic portfolio, risk, and execution decisions.

It began as a system for answering a simple question — **“How could tariffs and geopolitical pressure affect markets?”** — and has grown into a broader institutional-style research desk with historical replay, governed machine learning, durable execution accounting, immutable decision auditing, operator safety controls, production-readiness checks, and counterfactual “what-if” analysis.

Think of it as a command center that sits between **“what is happening in the world?”**, **“what is happening in markets?”**, and **“what would the desk do under these conditions?”**

The project is still for research and development. Paper mode is the default. Intelligence, allocation, hedging, scenario, and counterfactual outputs are proposal/research tools rather than autonomous trading instructions.

---

## How It Works, Step by Step

### 1. Data Collection — The Inputs

The system continuously collects and normalizes data from multiple sources:

- **World Bank WITS** — tariff rates and trade-policy inputs.
- **GDELT** — global news tone/volume and geopolitical shock signals.
- **Pyth Network** — primary crypto oracle data.
- **Kraken** — spot-market price source and price-authority fallback.
- **CoinGecko** — additional price fallback.
- **Hyperliquid** — perpetual-market data and market microstructure.
- **Drift Protocol** — Solana perpetual-market and funding data.
- **yfinance / Stooq** — research-grade equity data with deterministic degraded/demo fallbacks when providers are unavailable.

The ingestion layer no longer treats these merely as anonymous snapshots. It now has a **Source Registry**, durable **ingest-run history**, and **data provenance** records that describe which provider/run produced data, provider timestamps, record counts, fallback usage, and failure state.

Redis leases coordinate scheduled ingestion when Redis is healthy so multiple workers do not duplicate the same job. Research ingestion remains fail-soft: provider failures are surfaced as degraded/unavailable rather than crashing the entire application.

### 2. Canonical State & Data Contracts

Provider-native data is preserved, but important shared state also has canonical identities so consumers do not silently disagree about symbols or key names.

Examples include:

- normalized Pyth/Kraken/CoinGecko price aliases;
- canonical WITS tariff aggregate state;
- stablecoin-health state;
- macro prediction state;
- price-integrity state.

Price integrity is intentionally truthful: `OK` requires actual cross-source validation. If there are not enough usable sources, integrity can be `UNKNOWN` rather than pretending everything is healthy.

### 3. Tariff Pressure & Macro Signals

The desk computes tariff- and shock-oriented macro signals using WITS and GDELT inputs. The Index area presents:

- tariff pressure/index levels;
- shock score;
- rate of change;
- historical views;
- macro-event timelines;
- WITS series and country weighting;
- prediction and market-reaction context.

The goal is not to assert that tariffs mechanically determine asset prices. The system makes the inputs, timestamps, drivers, and confidence visible so the user can interpret how macro pressure is feeding into deterministic research rules.

### 4. Market Monitoring

The Markets layer shows and analyzes:

- multi-source crypto prices;
- funding rates;
- carry scores;
- order-book imbalance and liquidity depth;
- bid/ask spread and basis;
- cross-venue price integrity;
- Solana execution quality;
- funding-arbitrage and basis opportunities;
- feed/source status.

The price-authority path uses the existing Pyth → Kraken → CoinGecko cascade for supported execution prices while retaining source attribution and freshness.

### 5. Divergence Detection

The Divergence layer monitors cross-venue price differences and dislocations. It provides spread calculations and alerts when the same market is behaving materially differently across sources/venues.

This is used as research and execution-quality context rather than as an autonomous arbitrage engine.

### 6. Stablecoin Monitoring

The Stablecoins layer watches peg health and liquidity conditions, including:

- USDC/USDT/DAI-style peg status;
- basis-point deviation;
- stress/depeg indicators;
- peg-break probability;
- stablecoin flow momentum;
- risk-on/risk-off interpretation;
- deterministic playbook/protection suggestions.

Stablecoin health is also consumed by ML, allocation, volatility, geopolitical, and portfolio-protection research paths.

### 7. Deterministic Strategy / Heuristic Engine

The rules engine contains versioned deterministic heuristics. Rules have stable IDs and versions so historical research can evaluate the **same rule version** that existed at decision time instead of silently falling forward to new logic.

Current heuristic families include tariff/volatility reduction, shock throttling, divergence/funding hedging, negative-carry reduction, and stablecoin rotation behavior.

Rules remain deterministic and explainable: when a rule fires, the output includes the rule identity/version, proposed action, reason, and historical decision timestamp when replayed.

### 8. Heuristic Performance Lab

The Strategy area includes a Historical Heuristic Performance Lab. It evaluates versioned heuristics against persisted event-time data and can measure:

- directional/classification performance;
- horizon outcomes;
- regime segmentation;
- decay over time;
- calibration/Brier-style statistics where applicable;
- historical evidence/sample counts.

The performance layer does not invent outcomes when realized history is missing. Missing history is reported as unavailable/unevaluated rather than fabricated performance.

### 9. ML Reliability & Model Governance

The ML layer has evolved beyond an in-memory training experiment.

It now includes:

- a versioned 15-feature schema;
- per-feature provenance (`observed`, `derived`, `fallback`, `default`);
- deterministic dataset manifests and SHA-256 identities;
- strict timestamp ordering and label-definition versioning;
- temporal walk-forward validation using sklearn pipelines;
- durable training-run and candidate-model records;
- immutable model versions;
- serialized artifact SHA-256 verification;
- explicit promote and rollback operations;
- restart-safe active-model loading;
- persisted prediction provenance and input hashes;
- heuristic fallback when a governed model is unavailable or invalid.

Training does **not** automatically promote a model, and model lifecycle changes are operator actions. Historical decision replay requires the exact historical model/version/artifact when ML was part of the decision.

### 10. Capital Allocation & Portfolio Proposals

The allocator produces proposal-only weights across:

- Hyperliquid;
- Drift;
- Jupiter Spot;
- stablecoins;
- cash.

It considers signals such as volatility regime, tariff shock, stablecoin health, funding opportunity, basis opportunity, execution quality, prediction confidence, and portfolio state.

Allocation output can feed a pre-trade sizing preview that compares a proposed order against target allocation, venue/asset caps, portfolio risk room, cash, and existing exposure. These are proposals — the allocator does not autonomously submit orders.

### 11. Historical Backtesting

The Backtest Lab now has two explicit modes:

#### Synthetic Research
The original deterministic seeded simulation remains available for research/demo compatibility.

#### Historical Event-Time
Historical mode consumes persisted observations and does **not** silently fall back to synthetic prices when history is missing. It can use market ticks, funding ticks, index history, stablecoin/regime observations, durable orders, and fills.

Historical replay enforces event-time ordering and avoids same-observation look-ahead. It supports:

- latency assumptions;
- maker/taker fees;
- slippage;
- full/fixed-partial fill assumptions;
- signed funding;
- PositionLedger accounting;
- realized/unrealized P&L;
- equity curves;
- Sharpe/drawdown/VaR/CVaR;
- optional walk-forward windows;
- durable backtest run metadata and data manifests.

### 12. PositionLedger & Durable Accounting

Paper execution uses a reusable `PositionLedger` for symmetric long/short accounting.

It handles:

- opening positions;
- partial reductions while preserving average entry;
- full closes;
- long↔short flips;
- gross/net realized P&L;
- mark-to-market unrealized P&L;
- fees;
- signed funding;
- slippage.

Historical replay reuses the same accounting boundary instead of maintaining separate incompatible P&L math.

### 13. Durable Order Lifecycle

Execution persistence is no longer centered only on a legacy `paper_trades` record.

The durable lifecycle includes normalized concepts such as:

- order intents;
- orders;
- order events;
- fills;
- paper orders;
- conditional orders;
- triggered/OCO state.

A submitted/acknowledged response is not automatically treated as a fill. Uncertain live-submission states can be marked as requiring reconciliation instead of being replaced with fake paper fills.

Conditional orders are durable and use atomic PostgreSQL trigger claims to reduce duplicate-worker execution risk.

### 14. Shared Redis Runtime & Risk State

Redis now has one shared process-level runtime boundary with bounded sync/async pools, health/reconnect telemetry, optional key prefixes, pub/sub helpers, idempotency helpers, and lease support.

PostgreSQL remains the durable source of truth for orders/fills/decisions. Redis is used for low-latency runtime state such as:

- snapshots;
- pub/sub/WebSocket fanout;
- execution idempotency;
- ingest leases;
- shared risk throttle;
- shared daily realized P&L;
- shared live cooldown state.

Paper/research behavior can degrade to local/process fallback where appropriate. Live new exposure has stricter fail-closed requirements.

### 15. Risk Management

The RiskEngine evaluates portfolio/account state rather than only simplistic position lists. It can calculate:

- gross and net leverage;
- margin utilization;
- asset/venue/strategy concentration;
- liquidation buffer;
- projected leverage after a proposed action;
- projected margin usage;
- daily-loss constraints;
- shared throttle/cooldown state.

The system preserves a key safety property: a confirmed **pure risk reduction** can escape many new-exposure constraints so infrastructure/risk throttles do not unnecessarily trap an existing position.

The Risk tab also includes portfolio VaR/CVaR, stress tests, Monte Carlo research, volatility regimes, liquidation views, regime analogs and hedge/protection proposals.

### 16. Final Pre-Trade Decision Boundary

A major current architecture boundary is the deterministic pre-trade decision flow:

```text
Execution Request
      ↓
Data / Price Guardrails
      ↓
Historical/Current Risk Evaluation
      ↓
Execution-Agent Evaluation
      ↓
Deterministic ALLOW / BLOCK
      ↓
Immutable Final Decision Audit
      ↓
If allowed: submission
```

The final decision is produced by a pure combiner shared with replay. It is not copied from a stored target.

An allowed API-linked live order cannot bypass the final immutable audit persistence requirement for new exposure.

### 17. Immutable Decision Audit Ledger

The system maintains an append-only `decision_audit` ledger.

The original execution admission record is retained as an **admission intent**. After the real pre-trade data/risk/execution-agent checks, the router appends a separate immutable `execution_pre_trade_final` record before submission.

Decision records can include:

- input state;
- input provenance;
- derived state;
- heuristic result;
- ML result;
- risk result;
- allocation result;
- execution intent;
- component versions;
- configuration snapshot;
- final decision;
- canonical SHA-256 decision hash.

### 18. Exact Decision Replay

`POST /api/decisions/{decision_id}/replay` reconstructs a historical decision from the immutable audit record.

Replay can recompute:

- exact heuristic versions;
- exact governed ML artifacts;
- historical risk with an inert/no-Redis runtime;
- allocation using the original decision timestamp;
- execution data/agent checks;
- the deterministic final ALLOW/BLOCK decision.

Results are explicitly one of:

- `EXACT MATCH`;
- `MISMATCH` with structured field differences;
- `UNAVAILABLE` when the exact historical requirements do not exist.

Replay is audit-only and submits zero orders.

### 19. Counterfactual Decision Replay

Counterfactual replay extends **“What DID the desk decide?”** into **“What WOULD the same historical system have decided if specific inputs had been different?”**

Before a counterfactual can run, the original decision must reproduce as an exact baseline. The system then deep-copies historical replay inputs and applies only explicit semantic overrides.

Examples include:

- higher/lower shock score;
- different volatility regime;
- lower stablecoin health;
- wider execution spread;
- thinner liquidity;
- different fill price/order size;
- different historical daily P&L;
- different historical throttle state.

Mappings are explicit. Similar-sounding but different variables are not silently treated as the same thing. Components recorded as `not_used` stay `not_used`.

Counterfactual output shows original vs what-if components and whether the final decision changed. It is research-only: it writes no audit row, changes no model, reads no current live Redis state, and submits no order.

### 20. Operator Authorization

State-changing external surfaces can require a small operator bearer token:

```text
Authorization: Bearer <operator-token>
```

The system intentionally does not introduce a full user-account/OAuth platform yet.

Protected surfaces include order/conditional/smart-order mutations, ML training/promotion/rollback, manual decision writes, persisted heuristic evaluation, backtests, and watchlist mutations.

Any live-capable configuration forces operator authorization even if the explicit paper-mode auth flag was left disabled. If auth is required but no server token is configured, protected mutations fail closed.

The browser stores an operator token in `sessionStorage` only and attaches it only to protected mutations.

### 21. Jupiter / Solana Safety

Jupiter remains a separate spot-swap research integration. It is not forced through the perp-oriented execution router.

Direct Jupiter execution defaults to disabled:

```text
ENABLE_DIRECT_JUPITER_SWAP=false
```

The current Jupiter/Solana execution integration remains prototype-only and must not be interpreted as production-ready live execution.

### 22. Liveness vs Production Readiness

The application now distinguishes **process health** from **safe operational readiness**.

- `GET /live` / `/api/health/live` — is the API process responsive?
- `GET /ready` / `/api/health/ready` — is the configured instance ready for its intended mode?

Readiness checks include:

- PostgreSQL connectivity;
- required execution/audit schema;
- Redis/shared risk state;
- market-price availability/freshness;
- price integrity;
- ingestion visibility;
- risk-policy sanity;
- operator-auth configuration;
- execution-mode configuration;
- production-ready executor availability.

Paper/research mode can remain usable while degraded. Live-capable mode reports `NOT READY` when critical live dependencies are missing. The current live venue adapters are still prototype-only, so readiness truthfully does not claim production live-execution capability today.

### 23. Equities Research Layer

The desk includes a stock-market research view focused on tariff-sensitive equities and ETFs.

It can analyze broad indices/ETFs, sector ETFs, semiconductor/defense/retail/China/EM exposure, and tariff-sensitive companies. Research analytics include returns, volatility, drawdown, moving averages, RSI, beta proxy, relative strength, volume changes, sector labels and provider state.

Equity agents provide deterministic tariff/risk/sector-rotation signals. Provider failures degrade safely rather than crashing the application.

### 24. Institutional Intelligence Layer

The institutional layer connects macro/trade events to multi-asset reactions. It includes:

- macro event calendar and reaction estimates;
- tariff beta / macro sensitivity;
- cross-asset correlations and contagion paths;
- proposal-only scenario builder;
- cross-asset hedging;
- portfolio/recommendation explainability;
- agent consensus;
- signal outcome attribution;
- custom watchlists;
- structured JSON risk reports.

### 25. Geopolitical Risk Intelligence

The Geopolitics workflow extends the desk into:

- sanctions and export controls;
- conflict escalation;
- shipping chokepoints;
- supply-chain pressure;
- energy/commodity shocks;
- cross-asset geopolitical market impact;
- proposal-only portfolio protection.

A 0–100 Geopolitical Market Risk Index summarizes current conditions with drivers, affected regions/assets, provider state, confidence and data-quality information.

Geopolitical and sanctions outputs are research aids, not legal, financial or investment advice.

### 26. AI / Heuristic Agents

The original deterministic agent system remains part of the desk, and the broader platform now includes additional equity/geopolitical/protection agents alongside the earlier risk, macro, execution, liquidity, Hyperliquid, Jupiter and hedging agents.

Agent outputs remain structured and explainable, with fields such as confidence, severity, direction, proposed action, reasoning and data timestamps. Missing realized outcomes remain unevaluated rather than being synthesized.

---

## The Dashboard

The frontend remains a single-page vanilla HTML/CSS/JavaScript application with Chart.js. Current top-level tabs include:

1. **Index** — Tariff Pressure Index, shock, prediction, macro events and Macro Terminal.
2. **Markets** — Prices, funding, carry, microstructure, Solana quality, funding arb, basis and feed status.
3. **Divergence** — Cross-venue spreads and alerts.
4. **Stablecoins** — Peg/stress monitoring and stable-flow intelligence.
5. **Strategy** — Rules, Heuristic Performance Lab, allocation, ML governance, strategy performance and Backtest Lab.
6. **Execution** — Order entry, safety status, lifecycle, positions, accounting, conditional and smart paper-order tools.
7. **Equities** — Equity overview, tariff exposure, sector/macro sensitivity, cross-asset research and watchlists.
8. **Geopolitics** — Geopolitical risk, sanctions, conflicts, shipping/energy shocks, scenarios, protection and reports.
9. **Risk** — Shared risk state, portfolio risk, stress/Monte Carlo, volatility regime, liquidation and hedging/protection context.
10. **Agents** — Agent registry/signals, consensus, history/performance and attribution.
11. **Decision Audit** — Immutable decision detail, exact replay and Counterfactual Decision Replay.

An event timeline and live WebSocket delivery remain part of the desk experience.

### UI Features

- Dark/light theme.
- Auto-refresh controls.
- WebSocket live updates with reconnect behavior.
- REST refreshes using `Promise.allSettled` so partial provider failures do not blank an entire tab.
- Freshness/degraded badges.
- Historical backtest controls.
- Operator-access UI using session-only token storage.
- Decision Audit replay and counterfactual panels explicitly labeled research/audit only.

---

## Technical Architecture

- **Backend:** Python + FastAPI.
- **Frontend:** vanilla HTML/CSS/JavaScript + Chart.js; no React.
- **Durable storage:** PostgreSQL through the existing psycopg2 repository/helper pattern and `migrations.sql`.
- **Realtime/coordination:** Redis for snapshots, idempotency, leases, risk runtime state, pub/sub and WebSocket fanout.
- **Ingestion:** APScheduler plus explicit source/provenance tracking.
- **Execution:** paper-first ExecutionRouter, durable order/fill lifecycle, PositionLedger, shared RiskEngine, final-decision audit.
- **ML:** versioned features/datasets, temporal candidate training, immutable model registry, explicit promotion/rollback, exact artifact replay.
- **Audit/research:** exact decision replay plus research-only counterfactual replay.

The repository intentionally does not require SQLAlchemy, asyncpg, Alembic, Kubernetes, Kafka, Celery, or a separate observability stack for the current architecture.

### Safety Design

- Paper mode by default.
- Independent `LIVE_EXECUTION_ENABLED` gate.
- Prototype live adapters remain non-production-ready.
- Operator authorization on state-changing surfaces when required.
- Redis idempotency and durable intent required for API-linked live new exposure.
- Pure reductions retain carefully scoped degraded-mode escape behavior.
- Price freshness/integrity guardrails.
- Shared portfolio-aware risk state.
- Immutable final pre-trade decision audit before allowed submission.
- Direct Jupiter swaps independently disabled by default.
- `/ready` refuses to label unsafe live configuration as ready.
- Replay and counterfactual paths are unable to submit orders.

---

## Environment and Configuration

The application can be started with `python main.py`. PostgreSQL and Redis are external runtime dependencies configured through environment variables rather than processes owned by the application.

Important settings include:

- `DATABASE_URL`
- `REDIS_URL`, pool/timeouts/key-prefix/lease settings
- `EXECUTION_MODE` — `paper` by default
- `LIVE_EXECUTION_ENABLED` — independent live gate, default false
- `OPERATOR_API_TOKEN`
- `OPERATOR_AUTH_REQUIRED`
- `ENABLE_DIRECT_JUPITER_SWAP` — default false
- supported execution venues/markets/order types
- `MAX_ORDER_NOTIONAL`, `MAX_ORDER_SLIPPAGE_BPS`
- `MAX_LEVERAGE`, `MAX_MARGIN_USAGE`, `MAX_DAILY_LOSS`, `COOLDOWN_SECONDS`
- `PRICE_FRESHNESS_THRESHOLD_S`, `PRICE_INTEGRITY_BLOCK_LIVE`
- Pyth/Hyperliquid/Drift/Solana/Jupiter provider settings

Secrets are not exposed in configuration-summary responses.

## Test Coverage

The repository now has many focused regression modules beyond the older test-count snapshots in this document. Coverage includes execution safety, PositionLedger accounting, durable lifecycle, Redis/runtime reliability, historical backtesting, frontend alignment, heuristic performance, ingestion provenance, state contracts, ML governance, decision audit, audit correctness, risk unification, operator authorization, readiness and counterfactual replay, along with equity/institutional/geopolitical intelligence tests.

Use:

```bash
pytest -q
```

or `pytest --collect-only -q` when an exact current test count is needed.

---

## Current Product Position

The desk is no longer only a tariff-index dashboard or a paper-trading demo. It is now a research-grade macro/market decision system with explicit historical lineage, deterministic decision logic, governed ML, durable execution accounting, immutable auditability, reproducible replay, operational safety gates and counterfactual scenario analysis.

The next feature work can build on those foundations without needing another broad infrastructure rewrite. Paper/research mode remains the correct default while production live venue adapters remain intentionally gated.
