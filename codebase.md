# Tariff Risk Desk — Codebase Guide

> **Current state (August 2026):** post-PR #24 · paper/research default · durable execution lifecycle · shared Redis risk/runtime coordination · historical event-time replay · ingestion provenance · governed ML · immutable decision audit · exact replay · operator authorization · mode-aware production readiness · research-only counterfactual replay.

This guide describes the current repository while preserving the major equity, institutional-intelligence, geopolitical, execution-safety, and research layers added earlier in the project.

The repository has grown substantially beyond the older Phase-6/count snapshots. Exact file/test counts change as focused regression suites are added, so this guide describes authoritative modules and boundaries instead of freezing another stale count.

---

## Root

| File | Purpose |
|------|---------|
| `main.py` | FastAPI entry point. Mounts `/frontend`, registers API/probe routers, applies PostgreSQL migrations through the existing DB helper, starts/stops APScheduler, installs the operator-auth HTTP boundary, injects additive frontend compatibility/security/replay scripts, and closes Redis/PostgreSQL resources during lifespan shutdown. |
| `README.md` | **Primary current project overview and architecture/status document.** |
| `Summary.md` | Plain-English product/system walkthrough. |
| `codebase.md` | This file — technical repository guide. |
| `changelog.md` | Chronological feature/hardening history, updated through PR #24. |
| `Explanation.md` / `explanation.md` | Extended architectural explanation where present; use `README.md` as the primary current-state source. |
| `pyproject.toml` | Python package/dependency definition. Current stack remains FastAPI + psycopg2 + Redis + scientific/ML libraries; no SQLAlchemy/asyncpg/Alembic migration. |

Use `README.md` for the current repository architecture and project status.

---

# Backend (`backend/`)

The backend remains organized into these broad packages:

- `api/` — HTTP/WebSocket surfaces
- `core/` — shared runtime, safety, state, accounting, schemas
- `compute/` — deterministic analytics/replay/risk/research logic
- `agents/` — deterministic heuristic agents
- `ml/` — governed ML feature/dataset/training/inference lifecycle
- `ingest/` — provider collection, source registry and provenance
- `execution/` — paper/prototype venue execution adapters and routing
- `data/` — psycopg2 DB helper, migrations and repositories

The current design deliberately keeps the PostgreSQL/Redis helper pattern rather than introducing a second persistence framework.

---

## `backend/config.py` — Environment & Safety Configuration

Centralized configuration includes:

### Database / Redis
- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_KEY_PREFIX`
- `REDIS_MAX_CONNECTIONS`
- `REDIS_CONNECT_TIMEOUT_S`
- `REDIS_SOCKET_TIMEOUT_S`
- `REDIS_HEALTH_CHECK_INTERVAL_S`
- `REDIS_LEASE_TTL_S`
- `REDIS_PUBSUB_RETRY_S`

### Execution
- `EXECUTION_MODE` (`paper` default, or `live`)
- `LIVE_EXECUTION_ENABLED` — second independent live gate, default `false`
- `SUPPORTED_EXECUTION_VENUES`
- `SUPPORTED_EXECUTION_MARKETS`
- `SUPPORTED_ORDER_TYPES`
- `MAX_ORDER_NOTIONAL`
- `MAX_ORDER_SLIPPAGE_BPS`

### Operator / Jupiter safety
- `OPERATOR_API_TOKEN`
- `OPERATOR_AUTH_REQUIRED`
- `ENABLE_DIRECT_JUPITER_SWAP` — default `false`

Any live-capable configuration forces operator auth through `backend/core/operator_auth.py`, regardless of the explicit paper/research auth flag.

### Risk / market data
- `MAX_LEVERAGE`
- `MAX_MARGIN_USAGE`
- `MAX_DAILY_LOSS`
- `COOLDOWN_SECONDS`
- `PRICE_FRESHNESS_THRESHOLD_S`
- `PRICE_INTEGRITY_BLOCK_LIVE`

### Provider configuration
- Pyth Hermes URL/API-key state
- Hyperliquid/Drift/Solana/Jupiter settings
- WITS countries/products
- GDELT keywords

`config.summary()` exposes safe configured/not-configured metadata without returning operator/Pyth/private-key secrets.

---

# `backend/core/` — Shared Runtime & Safety Infrastructure

## `position_ledger.py`

Reusable position/accounting math used by paper execution and historical replay.

Handles:
- long/short opens
- partial reductions
- full closes
- long↔short flips
- average-entry preservation
- realized/unrealized P&L
- fees
- signed funding
- slippage
- funding-only credits/debits for historical replay

This prevents separate execution/backtest accounting formulas from drifting apart.

## `risk_policy.py`

Shared configured risk-policy/runtime boundary. Supplies the same environment-defined leverage, margin, daily-loss and cooldown settings to risk/execution consumers and exposes Redis-backed shared throttle, daily realized P&L and live cooldown state.

## `redis_runtime.py`

Process-level Redis runtime boundary:
- bounded sync/async pools
- connect/socket timeouts
- health/reconnect telemetry
- optional key namespace
- publish/pubsub helpers
- graceful shutdown

This replaced independent Redis clients and application-owned Redis process behavior.

## `state_store.py`

Realtime snapshot/coordination interface over the shared Redis runtime, with process fallback where research semantics allow it.

Also provides:
- execution idempotency claim/get/release helpers
- distributed lease helpers
- snapshot reads/writes
- compatibility behavior for older keys

PostgreSQL remains the durable source of truth for order/fill/decision history.

## `state_keys.py`

Canonical state-key contract for normalized producer/consumer identities:
- Pyth/Kraken/CoinGecko price aliases
- WITS aggregate state
- GDELT-related state
- stablecoin health
- prediction
- price integrity

Provider-native keys remain available where useful for provenance/compatibility.

## `operator_auth.py`

Minimal operator Bearer-token boundary for state-changing external routes.

Key behavior:
- constant-time token comparison
- live-capable mode always requires auth
- missing required server token fails closed
- explicit route/pattern classification for mutations
- read-only/research calculation POSTs are not automatically treated as writes
- direct Jupiter swap has an independent default-off feature gate

This is intentionally not a full user-account/OAuth/JWT platform.

## `readiness.py`

Mode-aware operational readiness aggregation over existing contracts:
- PostgreSQL
- required live schema
- Redis
- market-price availability/freshness
- price integrity
- ingestion visibility
- risk runtime/policy sanity
- operator authorization
- execution configuration
- production-ready executor availability

Paper/research can remain available while degraded. Live-capable mode fails readiness when a critical prerequisite is missing.

## Other core modules

| File | Role |
|------|------|
| `event_bus.py` | Unified event persistence + Redis pub/sub fanout across execution lifecycle, risk, ingestion, governance, audit and market/product events. |
| `price_authority.py` | Pyth → Kraken → CoinGecko execution price cascade with source attribution. |
| `price_validator.py` | Cross-source integrity/deviation evaluation; insufficient source coverage does not falsely become `OK`. |
| `schemas.py` / `models.py` | Typed/Pydantic contracts including portfolio/risk structures. |
| `normalization.py` | Provider normalization utilities. |
| `timeutils.py` | UTC/window helpers. |

---

# `backend/api/` — HTTP & WebSocket Surfaces

The API surface has expanded well beyond the earlier Phase-6 route table. `main.py` is the authoritative router registration list.

## Core market / macro

| Router | Main purpose |
|--------|--------------|
| `index_routes.py` | Tariff/index latest/history/components/macro-terminal views. |
| `markets_routes.py` | Multi-source prices, funding and price integrity. |
| `divergence_routes.py` | Cross-venue spread/dislocation analysis. |
| `stablecoin_routes.py` | Peg/stress/stablecoin health. |
| `predict_routes.py` | Macro prediction. |
| `macro_routes.py` | Macro/trade event timeline and reaction research. |
| `macro_sensitivity_routes.py` | Tariff beta / macro sensitivity. |
| `cross_asset_routes.py` | Correlation and contagion research. |

## Execution / risk

| Router | Main purpose |
|--------|--------------|
| `execution_routes.py` | Primary order path, positions/trades, conditional orders, smart orders, lifecycle-linked execution requests and direct Jupiter route. Protected mutations use operator auth when required. |
| `risk_routes.py` | Risk status/guardrails/stress/regime-analog views using the shared RiskEngine policy/runtime. |
| `allocation_routes.py` | Capital allocation proposals, rebalance preview and allocation→execution sizing preview. |
| `portfolio_risk_routes.py` | Portfolio exposure/VaR/CVaR/concentration detail. |
| `liquidation_routes.py` | Liquidation heatmap. |
| `slippage_routes.py` | Slippage curves/safe-size research. |
| `hedge_routes.py` | Asset/cross-asset hedge research and previews. |
| `protection_routes.py` | Proposal-only portfolio protection status/previews. |

## Research / historical evaluation

| Router | Main purpose |
|--------|--------------|
| `backtest_routes.py` | Synthetic research + historical event-time backtest, durable run history and data coverage. |
| `heuristic_routes.py` | Versioned heuristic registry, persisted evaluation, performance and evaluation history. |
| `sandbox_routes.py` | Strategy A/B research comparison. |
| `replay_routes.py` | Event/trade simulation research surfaces; distinct from immutable decision replay. |
| `scenario_routes.py` | Proposal-only scenario research. |

## Decision Audit — `decision_routes.py`

Current decision endpoints include:
- `POST /api/decisions` — explicit/manual decision-record creation
- `GET /api/decisions`
- `GET /api/decisions/{decision_id}`
- `POST /api/decisions/{decision_id}/replay` — exact historical replay
- `POST /api/decisions/{decision_id}/counterfactual` — research-only what-if replay

Replay/counterfactual endpoints are calculation-only and never route an order.

## ML Governance — `ml_routes.py`

Current ML routes cover:
- feature/latest prediction views
- offline candidate training
- durable training history/runs
- model registry / active model
- model health
- dataset registry
- explicit promote/rollback
- ML-vs-heuristic comparison using exact timestamp/sample alignment

Training/promote/rollback are operator mutations when auth is required.

## Ingestion / operations

| Router | Main purpose |
|--------|--------------|
| `ingestion_routes.py` | Source Registry, ingestion health/status, run history and artifact provenance. |
| `health_routes.py` | Existing system/feed/Redis/data-quality health plus `/api/health/live` and `/api/health/ready`. |
| root probe router | `/live` and `/ready`. |
| `events_routes.py` | Durable event history. |
| `ws_routes.py` | WebSocket event delivery through shared Redis async pub/sub. |

## Institutional / geopolitical research

The earlier product layers remain registered through routers including:
- `equities_routes.py`
- `strategy_routes.py`
- `agents_routes.py`
- `signals_routes.py`
- `watchlists_routes.py`
- `reports_routes.py`
- `explain_routes.py`
- `geopolitical_routes.py`
- `protection_routes.py`
- funding/basis/stable-flow/metrics/Solana/microstructure/yield routes

---

# `backend/compute/` — Deterministic Analytics, Replay & Decisions

## `execution_decision.py`

Pure deterministic final pre-trade helpers shared by runtime execution and replay:
- data guardrail evaluation
- execution-agent evaluation
- final ALLOW/BLOCK combination

The combiner submits no orders, persists nothing and reads no Redis state.

## `decision_evaluator.py`

Pure component evaluators for exact replay:
- exact heuristic version
- exact governed ML artifact
- historical risk using inert runtime state
- deterministic allocation with historical `as_of`
- final execution-boundary recomputation

This lets runtime/replay share decision semantics rather than approximating each other.

## `decision_replay.py`

Canonical decision hashing and exact replay:
- stable SHA-256 hash
- timestamp/decimal/JSON normalization
- structured field diffs
- exact artifact/version verification
- `EXACT MATCH`, `MISMATCH`, `UNAVAILABLE`
- `audit_only=true`
- `orders_submitted=0`

It deliberately does not import execution routing, StateStore or Redis.

## `counterfactual_replay.py`

Research-only what-if replay over immutable historical inputs:
1. require exact baseline replay;
2. deep-copy recorded inputs;
3. apply allowlisted semantic overrides;
4. preserve `not_used` components;
5. preserve heuristic/model/policy identities;
6. invoke existing deterministic evaluators;
7. compare original vs counterfactual results/final decision.

No persistence or execution is performed.

## Risk / allocation / execution research

| File | Role |
|------|------|
| `risk_engine.py` | Portfolio-aware leverage/margin/daily-loss/throttle/cooldown enforcement with pure-reduction detection and historical `as_of` support. |
| `capital_allocator.py` | Proposal-only venue allocation plus execution sizing preview. |
| `smart_execution.py` | TWAP/VWAP planning/status for paper/proposal workflows. |
| `slippage_model.py` | Slippage curves/safe-size research. |
| `execution_metrics.py` | Execution Quality Index and fill/slippage statistics. |
| `liquidation_heatmap.py` | Leverage/price-drop liquidation grid. |
| hedge/cross-asset modules | Hedge ratio and cross-asset proposal research. |

## Historical evaluation

### Historical backtester
Supports:
- deterministic synthetic research;
- persisted historical event-time replay;
- strict event ordering / look-ahead protection;
- latency/fees/funding/slippage/partial fills;
- PositionLedger accounting;
- durable run metadata and manifests.

Historical mode has no hidden synthetic fallback.

### `heuristic_performance.py`
Evaluates stable rule IDs/versions on persisted event-time observations with horizon outcomes, classification/risk-control metrics, regime segmentation and decay analysis. Missing realized history is not fabricated.

## Existing market / institutional compute layers

The earlier functionality remains, including:
- tariff/index/shock computation
- divergence/regime/carry
- stablecoin health/flow/playbook
- Monte Carlo and stress tests
- microstructure
- funding arb / basis
- portfolio optimization
- volatility regime
- equity analytics / tariff exposure
- macro events / sensitivity
- cross-asset intelligence
- scenario engine
- explainability
- agent consensus / signal attribution
- geopolitical/sanctions/conflict/shipping/energy risk
- portfolio protection
- report generation / watchlists

---

# `backend/ml/` — Governed ML Lifecycle

The governed PostgreSQL/model-registry path is now authoritative rather than an older process-only trained-model description.

## `feature_store.py`
- 15-feature schema
- schema ID/version
- deterministic feature ordering
- observed/derived/fallback/default provenance
- quality counts/ratios

## `dataset.py`
- label definition ID/version
- strict temporal ordering
- deterministic vectors
- SHA-256 dataset manifest
- provenance summary

## `training.py`
- offline candidate training
- explicit supported method handling
- sklearn pipeline/scaling
- temporal walk-forward validation
- validation samples/metrics
- durable training/model records
- no automatic promotion

## `governance.py`
- artifact serialization/deserialization
- SHA integrity checks
- promotion/rollback eligibility
- model-health inspection

## `inference.py`
- durable active-model lookup
- schema/artifact verification
- restart-safe loading/caching
- prediction provenance/input hash persistence
- explicit heuristic fallback

## `backend/data/repositories/ml_repo.py`
Durable datasets, training runs, immutable model versions and predictions. Activation is transactional.

---

# `backend/ingest/` — Source Registry, Collection & Provenance

Important current files include:
- `source_registry.py` — stable source IDs, cadence, native/canonical snapshot identities and fallback metadata
- `provenance.py` — `IngestRunContext`
- `scheduler.py` — APScheduler + Redis lease coordination + run-ledger lifecycle
- WITS, GDELT, Pyth, Kraken, CoinGecko, Drift and Hyperliquid provider modules
- equity provider modules such as yfinance/Stooq

WITS/GDELT and market providers report fallback/degraded state explicitly. Hyperliquid WebSocket state can appear in the Source Registry without pretending it is a scheduled durable ingest run.

---

# `backend/execution/` — Paper & Prototype Live Execution

## `router.py`

Primary flow:

```text
request validation
    ↓
price/data guardrails
    ↓
RiskEngine
    ↓
ExecutionAgent
    ↓
pure final ALLOW/BLOCK
    ↓
immutable execution_pre_trade_final audit
    ↓
if allowed → paper/selected executor
```

Also:
- uses PriceAuthority when price is omitted;
- records source/freshness/integrity context;
- produces replayable risk/data/agent inputs;
- preserves pure-reduction safety semantics;
- fails API-linked live new exposure when required final audit persistence is unavailable.

## `paper_exec.py`
Paper simulator backed by PositionLedger/accounting and durable order/fill lifecycle persistence.

## `hyperliquid_exec.py` / `drift_exec.py`
Prototype live venue adapters. Current readiness intentionally does not treat them as production-ready.

## Jupiter / Solana execution helpers
Separate spot-swap prototype path. Direct API execution has its own default-off gate and operator authorization requirement; it is not represented as equivalent to the hardened perp-style primary order pipeline.

---

# `backend/data/` — PostgreSQL Durable State

## `db.py`

Psycopg2 `ThreadedConnectionPool` helper with:
- lazy shared pool
- migration application through `migrations.sql`
- PostgreSQL advisory lock around migrations
- connection/query helpers
- required-table readiness check
- idempotent shutdown

No SQLAlchemy/asyncpg/Alembic layer is used.

## Important repositories

| Repository | Responsibility |
|------------|----------------|
| `orders_repo.py` | Order intents, orders, order events, fills, paper orders, conditional orders, trigger claims/OCO lifecycle. |
| `backtest_repo.py` | Durable backtest run/config/window/manifest/status/metrics. |
| `heuristic_repo.py` | Persisted heuristic evaluations/performance queries. |
| `ingest_repo.py` | Ingest runs, reliability/failure tracking and data provenance. |
| `ml_repo.py` | Governed datasets, training runs, model versions, predictions and transactional activation. |
| `decision_repo.py` | Immutable decision-audit create/get/list boundary. No mutable finalize/update operation. |
| existing market/index/event/position repositories | Durable research/market/history data. |

## Schema families

`migrations.sql` now covers:
- market/index/funding/stablecoin/regime history
- events
- positions / legacy paper compatibility
- order intents / orders / events / fills / paper orders
- conditional orders
- backtest runs
- heuristic evaluations
- ingest runs / data provenance
- ML datasets / training runs / models / predictions
- immutable `decision_audit`

The database remains additive/backward-compatible rather than replacing historical tables wholesale.

---

# Frontend (`frontend/`)

Single-page vanilla HTML/CSS/JavaScript + Chart.js. No React/build-system migration.

## `frontend/index.html`

Current top-level product areas:
- Index
- Markets
- Divergence
- Stablecoins
- Strategy
- Execution
- Equities
- Geopolitics
- Risk
- Agents
- Decision Audit

## `frontend/assets/api.js`
Central REST client for older market/intelligence panels plus historical backtests, heuristics, ingestion/provenance, ML governance, durable decision audit/replay, execution lifecycle/safety and institutional/geopolitical surfaces.

## `frontend/assets/app.js`
Main tab/form orchestration for WebSocket + REST refreshes, orders, stress/Monte Carlo/backtests, heuristic lab, institutional/geopolitical forms and decision selection/replay.

## `frontend/assets/ui.js`
Main renderer collection, including historical Backtest Lab, execution safety/lifecycle/accounting, Redis telemetry, portfolio risk, heuristic performance, ingestion/provenance, ML governance, Decision Audit and institutional/geopolitical panels.

## `frontend/assets/frontend_alignment.js`
Compatibility stub retained after PR #12 moved temporary frontend-alignment behavior into the core UI. It should remain non-authoritative.

## `frontend/assets/operator_access.js`
Small operator-access enhancement:
- injects operator control into the existing header
- stores token in `sessionStorage`
- attaches bearer credentials only to classified protected mutations

## `frontend/assets/counterfactual_replay.js`
Research-only Decision Audit enhancement:
- counterfactual scenario inputs
- request to `/api/decisions/{id}/counterfactual`
- original-vs-counterfactual rendering
- applied/not-applicable scenario display
- explicit no-order/no-persistence/no-retraining labels

## `styles.css`, `charts.js`, `ws.js`
Existing theme system, Chart.js helpers and WebSocket reconnect behavior remain authoritative.

---

# Current Decision / Execution Safety Stack

```text
Production readiness
      ↓
Operator authorization (state-changing external surfaces)
      ↓
Request validation
      ↓
Live enable / venue / market / order-type gates
      ↓
Redis idempotency for API-linked live new exposure
      ↓
Durable order intent
      ↓
Price / data guardrails
      ↓
Shared portfolio-aware RiskEngine
      ↓
ExecutionAgent pre-trade check
      ↓
Deterministic final ALLOW/BLOCK
      ↓
Immutable final decision audit
      ↓
Execution submission
      ↓
Durable lifecycle / fills / reconciliation state
```

The stack uses independent barriers rather than treating any one check as sufficient.

---

# Liveness / Readiness

```text
GET /live
GET /ready
GET /api/health/live
GET /api/health/ready
```

`/live` answers whether the process can serve the request.

`/ready` answers whether the instance is safe/operational for its configured mode. Paper mode can be degraded yet usable. Live mode is blocked by missing critical database/schema, Redis/risk, market-data integrity/freshness, operator-auth or executor prerequisites.

---

# Historical Research Stack

Three distinct concepts:

### 1. Historical Backtester
Reconstructs strategy/trade behavior over persisted event-time market history.

### 2. Exact Decision Replay
Reconstructs one immutable audited decision using exact historical component identities and inputs.

### 3. Counterfactual Decision Replay
Requires an exact replayable baseline, then changes explicitly allowlisted historical inputs and asks what the **same historical system** would have decided.

All are research/audit paths and are separate from live submission.

---

# Earlier Product Layers Still Present

## Equity + Execution Safety Expansion
- yfinance/Stooq fail-open equity ingestion
- equity analytics and tariff exposure
- equity risk/tariff/sector agents
- allocation execution preview
- conditional paper orders
- TWAP/VWAP smart-order planning
- strategy performance
- data-quality views
- replay trade simulation
- agent history/performance
- Equities tab

## Institutional Intelligence Layer
- macro events / reaction estimates
- macro sensitivity / tariff beta
- cross-asset correlation/contagion
- scenario builder
- cross-asset hedge previews
- explainability
- agent consensus
- signal attribution
- watchlists
- structured reports

## Geopolitical Risk Intelligence Layer
- geopolitical risk index
- sanctions/export-control research
- conflict escalation
- chokepoints/shipping risk
- energy/commodity shock
- cross-asset market impact
- portfolio-protection proposals
- geopolitical agents/reports
- Geopolitics tab

These remain deterministic/proposal/research oriented and preserve degraded/fallback metadata when providers are unavailable.

---

# Tests (`tests/`)

Do not rely on the old fixed test-count statement. The suite now contains many focused files across hardening and product layers.

Important current suites include examples such as:
- `test_execution_safety.py`
- PositionLedger / paper-trading tests
- `test_durable_order_lifecycle.py`
- runtime / Redis reliability tests
- `test_historical_backtester.py`
- `test_frontend_alignment.py`
- `test_heuristic_performance.py`
- ingestion provenance/history tests
- state-contract tests
- `test_ml_governance.py`
- `test_decision_audit.py`
- `test_audit_governance_correctness.py`
- `test_final_decision_boundary.py`
- `test_risk_unification.py`
- `test_operator_auth.py`
- `test_production_readiness.py`
- `test_counterfactual_replay.py`
- equity/institutional/geopolitical intelligence tests

Run:

```bash
pytest -q
```

For a current exact count without running tests:

```bash
pytest --collect-only -q
```

---

# Current Non-Goals / Boundaries

The current codebase intentionally does **not** imply that it has:
- production-ready live Hyperliquid/Drift/Jupiter execution;
- autonomous allocation/agent/ML trading;
- mutable decision-audit rows;
- hidden synthetic fallback for historical replay;
- automatic ML promotion;
- full user-account/OAuth infrastructure;
- SQLAlchemy/asyncpg/Alembic;
- Kubernetes/Docker orchestration as a requirement;
- Kafka/Celery/RabbitMQ;
- Prometheus/Grafana/OpenTelemetry as a required second observability stack;
- GitHub Actions/YAML-based CI as part of the recent readiness work.

The architecture is focused on **truthful research behavior, durable accounting, deterministic decision logic, explicit provenance, auditability, operational safety and paper-first execution**.

---

# Documentation Source of Truth

- **`README.md`** — current project overview, architecture and phase.
- **`Summary.md`** — plain-English system/product walkthrough.
- **`codebase.md`** — technical file/module guide.
- **`changelog.md`** — chronological evolution.

For final implementation truth, the code and migrations on `main` remain authoritative.
