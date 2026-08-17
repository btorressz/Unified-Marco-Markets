# Unified-Marco-Markets (Tariff Risk Desk)

**NOTE:** This project is for research and development purposes only at the moment. Paper/research mode remains the default. The current live venue adapters are still treated as prototype integrations and the application now reports live mode as not ready until a production-ready executor is available.

## Overview

Unified Macro Markets / Tariff Risk Desk is a unified macro-to-markets research, risk, execution-safety, and decision-audit platform. It transforms tariff, geopolitical, market-structure, stablecoin, equity, and cross-asset signals into deterministic research outputs, risk proposals, governed ML predictions, auditable execution decisions, historical replay, and counterfactual what-if analysis.

The project began as a tariff-pressure and crypto-market dashboard and has grown into a broader institutional-style research desk. It now includes equity and geopolitical intelligence, ingestion provenance, historical event-time backtesting, heuristic performance evaluation, ML model governance, durable order lifecycle accounting, shared Redis/PostgreSQL reliability controls, immutable decision auditing, exact decision replay, operator authorization, production-readiness probes, and research-only counterfactual replay.

## Current Phase — August 2026

The repository is now in a **post-hardening, research-feature phase**. The major reliability and audit sequence through PR #24 is merged:

- Durable execution lifecycle, PositionLedger accounting, order intents, fills, conditional-order persistence, and reconciliation-aware execution states.
- Shared Redis runtime, distributed leases, idempotency, shared risk throttle/daily P&L/cooldown state, and bounded Redis telemetry.
- Historical event-time backtester v2 using persisted observations with no hidden synthetic fallback.
- Historical Heuristic Performance Lab with versioned rules and persisted evaluation results.
- Ingestion Source Registry, ingest-run ledger, artifact provenance, canonical state/data contracts, and explicit fallback/degraded metadata.
- ML reliability and governance with deterministic dataset manifests, temporal validation, immutable model versions, exact artifact SHA verification, explicit promote/rollback, and durable training/prediction history.
- Immutable decision-audit ledger with exact replay, deterministic final-decision recomputation, and a true final pre-trade audit boundary before submission.
- Operator bearer-token protection for state-changing surfaces and an independent fail-closed gate for direct Jupiter swaps.
- `/live` and `/ready` production-readiness semantics for database/schema, Redis, market data, risk runtime, operator auth, ingestion visibility, and execution configuration.
- Research-only **Counterfactual Decision Replay** for asking what the same historical system would have decided under explicitly changed historical inputs.

No GitHub Actions, YAML/YML workflow layer, Kubernetes, Prometheus, Grafana, OpenTelemetry, SQLAlchemy, asyncpg, Alembic, Celery, Kafka, or other orchestration stack has been added as part of this hardening sequence.

## Core Design Principles

- **Paper/research by default.** `EXECUTION_MODE=paper` is the default and live execution has an independent `LIVE_EXECUTION_ENABLED` gate.
- **Fail-soft for research, fail-closed for live safety boundaries.** Missing research providers should degrade cleanly; live new exposure must not bypass critical execution, audit, idempotency, persistence, auth, or readiness requirements.
- **Deterministic and explainable.** Heuristics, replay, allocation, risk checks, decision combination, and counterfactual analysis use explicit inputs and versions.
- **Immutable audit history.** Decision records are append-only. Admission intent and final pre-trade decision are separate immutable records rather than mutable rows.
- **Historical truthfulness.** Historical replay never silently substitutes synthetic data, current Redis state, a newer model, or a newer heuristic version.
- **Proposal-only intelligence.** Allocation, hedging, equities, geopolitical analysis, scenario outputs, and counterfactuals do not autonomously trade.
- **No frontend framework migration.** The dashboard remains vanilla HTML/CSS/JavaScript with Chart.js.

## System Architecture

### Backend — Python / FastAPI

`main.py` creates the FastAPI application, mounts the frontend, registers the API routers, applies PostgreSQL migrations through the existing migration mechanism, starts the APScheduler ingestion scheduler, and closes Redis/PostgreSQL resources during shutdown.

Current router coverage includes:

- **Core market/macro data:** index, markets, divergence, stablecoins, prediction, events, macro events, macro sensitivity, cross-asset intelligence.
- **Risk and execution:** execution, risk, portfolio risk, allocation, slippage, liquidation, hedging, protection, execution quality.
- **Research and replay:** sandbox, replay simulation, historical backtest, heuristics, decision audit, exact replay, counterfactual replay.
- **ML governance:** features, inference, training, datasets, model registry, model health, promotion, rollback, comparison.
- **Institutional intelligence:** equities, scenarios, reports, explainability, watchlists, signal attribution, agent consensus, geopolitical intelligence.
- **Operations:** ingestion registry/provenance, health, Redis telemetry, liveness/readiness, WebSocket delivery.

### Compute Layer

Important current compute modules include:

- `risk_engine.py` — portfolio-aware pre-trade risk checks using configured limits and shared runtime state.
- `capital_allocator.py` — proposal-only allocation across Hyperliquid, Drift, Jupiter Spot, stablecoins, and cash.
- `historical_backtester.py` / backtest modules — deterministic historical event-time replay with persisted observations, fees, funding, latency, slippage, partial-fill assumptions, and PositionLedger accounting.
- `heuristic_performance.py` — event-time heuristic evaluation, horizon outcomes, regime segmentation, decay, and performance statistics.
- `execution_decision.py` — pure deterministic final pre-trade ALLOW/BLOCK combiner.
- `decision_evaluator.py` — exact recomputation of heuristic, governed ML, historical risk, allocation, and final execution-boundary results.
- `decision_replay.py` — canonical hashing, exact replay, structured differences, and `EXACT MATCH` / `MISMATCH` / `UNAVAILABLE` semantics.
- `counterfactual_replay.py` — research-only semantic what-if overrides applied to immutable replay inputs, followed by the same deterministic evaluators.
- `scenario_engine.py`, `cross_asset_intelligence.py`, `macro_sensitivity.py`, `geopolitical_risk.py`, `portfolio_protection.py` — proposal-only institutional and geopolitical research.

### ML Reliability & Governance

The ML package is no longer only an in-process training scaffold. The governed path now includes:

- `feature_store.py` — versioned 15-feature schema with observed/derived/fallback/default provenance.
- `dataset.py` — deterministic governed dataset manifests and SHA-256 identities with temporal ordering checks.
- `training.py` — offline candidate training with temporal splits; current governed implementation uses leak-resistant sklearn pipelines and records validation samples/metrics.
- `governance.py` — artifact serialization/integrity, eligibility, promotion, rollback, and model health.
- `ml_repo.py` — durable PostgreSQL storage for datasets, training runs, model versions, and predictions.
- `inference.py` — restart-safe active-model loading with artifact/schema validation and explicit heuristic fallback.

Model promotion and rollback are explicit operator actions. Counterfactual replay never changes model identity, version, artifact SHA, feature schema, or training state.

## Decision Audit, Exact Replay & Counterfactual Replay

The decision-audit path is a major current architecture boundary.

### Immutable decision records

Execution creates an immutable admission-intent record and, after actual data/risk/execution-agent evaluation, a separate immutable `execution_pre_trade_final` record before an allowed submission. The final record captures replayable inputs, risk state, data guardrails, execution-agent state, component versions, configuration snapshots, and the deterministic final decision.

### Exact replay

`POST /api/decisions/{decision_id}/replay` reconstructs historical results from stored inputs and exact component identities. Replay is read-only, never submits an order, never uses current Redis state, and returns `UNAVAILABLE` when the required exact historical inputs/model artifacts/versions do not exist.

### Counterfactual replay

`POST /api/decisions/{decision_id}/counterfactual` first requires the baseline decision to replay exactly. It then deep-copies historical replay inputs, applies only allowlisted semantic scenario overrides, and reuses the same deterministic evaluators. Examples include changes to shock score, volatility regime, stablecoin health, spread, liquidity depth, fill price, order size, historical daily P&L, or throttle state where those inputs were actually part of the recorded decision.

Counterfactual replay:

- does not mutate the original decision;
- does not persist a new audit row;
- does not route or submit orders;
- does not activate components recorded as `not_used`;
- does not change heuristic/model identities or risk-policy limits;
- reports original vs counterfactual results and whether the final ALLOW/BLOCK decision changed.

## Execution & Risk Safety

### Primary order path

The hardened primary order path includes:

1. Request and finite-number validation.
2. Operator authorization when required.
3. Live-mode and supported venue/market/order-type gates.
4. Redis idempotency for live new exposure.
5. Durable order intent.
6. Price availability/freshness/integrity guardrails.
7. Shared RiskEngine evaluation using portfolio/account state.
8. Execution-agent pre-trade evaluation.
9. Deterministic final ALLOW/BLOCK decision.
10. Immutable final decision audit persisted before allowed submission.
11. Venue/paper execution and durable lifecycle events.

Confirmed pure risk reductions retain degraded-mode escape behavior so infrastructure degradation does not unnecessarily trap exposure.

### Operator authorization

The application uses a deliberately small operator-access boundary rather than a user-account/OAuth system.

- `OPERATOR_API_TOKEN` supplies the bearer token.
- `OPERATOR_AUTH_REQUIRED` can require auth in paper/research deployments.
- Any live-capable configuration forces auth regardless of that explicit flag.
- State-changing execution, model-governance, backtest, persisted heuristic, watchlist, and manual decision-write surfaces are protected.
- Read-only/research calculation endpoints such as decision replay and counterfactual replay remain calculation-only.

The frontend stores an entered operator token in `sessionStorage` only and attaches it only to protected mutation requests.

### Jupiter direct-swap safety

Direct Jupiter swap execution is intentionally independent from the perp-style execution router and defaults to disabled with:

```text
ENABLE_DIRECT_JUPITER_SWAP=false
```

The current Jupiter/Solana live adapter remains prototype-only. It should not be treated as production-ready until a dedicated production spot-swap risk/signing/reconciliation path exists.

## Production Readiness

The application distinguishes liveness from readiness:

- `GET /live` and `GET /api/health/live` answer whether the API process is responsive.
- `GET /ready` and `GET /api/health/ready` answer whether the instance is operationally ready for its configured mode.

Readiness aggregates existing contracts for PostgreSQL connectivity, required execution/audit schema, Redis/shared risk state, fresh market-price data, price integrity, ingestion visibility, risk-policy sanity, operator-auth configuration, and execution configuration.

Paper/research mode may stay available while degraded. Live-capable mode reports `503 NOT READY` when a critical live dependency is unavailable. Current live executors are still marked prototype-only, so the readiness layer truthfully avoids declaring the system production-ready for live venue submission today.

## Data Ingestion & Provenance

APScheduler-driven sources include WITS, GDELT, Pyth, Kraken, CoinGecko, Drift and Hyperliquid market snapshots, with additional equity research providers such as yfinance/Stooq used in the equities layer.

The ingestion layer now includes:

- a code-defined Source Registry;
- durable ingest-run records;
- generic artifact/data provenance;
- provider timestamps, received/processed/persisted counts, fallback visibility, and failure state;
- Redis leases to prevent duplicate scheduled ingest work when Redis is available;
- canonical state keys plus compatibility aliases for market prices, WITS, stablecoin health, prediction, and price integrity.

## Frontend — Vanilla HTML/CSS/JS + Chart.js

The dashboard remains a single-page vanilla-JS application. Current top-level tabs include:

1. **Index** — tariff pressure, shock, macro events, prediction, macro terminal.
2. **Markets** — multi-source prices, funding, carry, microstructure, basis, funding arb, Solana quality, feed status.
3. **Divergence** — cross-venue spread/dislocation monitoring.
4. **Stablecoins** — peg health, stress, depeg risk, stable-flow intelligence.
5. **Strategy** — rules, Heuristic Performance Lab, allocation, ML reliability/governance, historical backtest, strategy performance.
6. **Execution** — order entry, execution safety, lifecycle, positions, accounting, advanced paper orders, smart-order views.
7. **Equities** — market overview, tariff-sensitive equities, sector rotation, macro sensitivity, cross-asset intelligence and watchlists.
8. **Geopolitics** — sanctions, conflicts, chokepoints, shipping/energy shocks, market impact, scenarios, protection proposals and risk briefs.
9. **Risk** — shared risk state, portfolio risk, stress tests, Monte Carlo, volatility regime, liquidation/regime/hedge views, readiness/telemetry context.
10. **Agents** — deterministic agent signals, consensus, history/performance and attribution.
11. **Decision Audit** — immutable decision detail, exact replay, and counterfactual what-if analysis.

Existing UX behavior remains: dark/light theme, Chart.js, WebSocket updates, REST polling, visibility-aware polling, freshness badges, and defensive renderers.

## Historical Backtesting

The backtester has two explicit modes:

- **Synthetic Research** — deterministic seeded simulation for research/demo compatibility.
- **Historical Event-Time** — persisted observations only; there is no hidden synthetic fallback when historical data is unavailable.

Historical mode can consume persisted market, funding, index, stablecoin, regime, order and fill observations. It enforces event-time ordering, prevents same-observation look-ahead, supports configurable latency/fees/slippage/partial fills, and reuses PositionLedger accounting. Backtest runs can be durably recorded with data-manifest and coverage metadata.

## Heuristic Performance Lab

Rules have stable IDs/versions and can be evaluated against persisted event-time observations. The Heuristic Performance Lab provides registry, evaluation, performance, and persisted evaluation APIs while preserving the existing deterministic rule behavior. Historical heuristic evaluation never fabricates missing historical outcomes.

## Equity, Institutional & Geopolitical Intelligence

The existing equity, institutional intelligence, and geopolitical sections remain active parts of the product:

- tariff-sensitive equities and ETFs;
- yfinance/Stooq research-grade ingestion with deterministic degraded/demo fallbacks;
- macro event calendar and reaction estimates;
- tariff beta/macro sensitivity;
- cross-asset correlation and contagion;
- proposal-only scenario builder and cross-asset hedging;
- explainability, consensus, attribution, watchlists and JSON reports;
- geopolitical risk index, sanctions/conflict/chokepoint/shipping/energy intelligence;
- proposal-only portfolio protection status and previews.

These outputs remain research/proposal-only and are not legal, financial, or investment advice.

## Configuration

Important current environment settings include:

```text
DATABASE_URL
REDIS_URL
REDIS_KEY_PREFIX
REDIS_MAX_CONNECTIONS
REDIS_CONNECT_TIMEOUT_S
REDIS_SOCKET_TIMEOUT_S
REDIS_HEALTH_CHECK_INTERVAL_S
REDIS_LEASE_TTL_S
REDIS_PUBSUB_RETRY_S

EXECUTION_MODE=paper
LIVE_EXECUTION_ENABLED=false
OPERATOR_API_TOKEN
OPERATOR_AUTH_REQUIRED=false
ENABLE_DIRECT_JUPITER_SWAP=false
SUPPORTED_EXECUTION_VENUES
SUPPORTED_EXECUTION_MARKETS
SUPPORTED_ORDER_TYPES
MAX_ORDER_NOTIONAL
MAX_ORDER_SLIPPAGE_BPS

MAX_LEVERAGE
MAX_MARGIN_USAGE
MAX_DAILY_LOSS
COOLDOWN_SECONDS
PRICE_FRESHNESS_THRESHOLD_S
PRICE_INTEGRITY_BLOCK_LIVE

PYTH_HERMES_URL
PYTH_API_KEY
HYPERLIQUID_API_KEY
DRIFT_RPC_URL
SOLANA_RPC_URL
SOLANA_PRIVATE_KEY
JUPITER_API_URL
```

Secrets are not returned in the configuration summary; only configured/not-configured state is exposed where appropriate.

## Database & Runtime

PostgreSQL is the durable source of truth for market history, lifecycle records, audit/governance records and other persisted research data. The schema has expanded well beyond the original `paper_trades`-centric layout and now includes normalized order lifecycle tables, ingest/provenance tables, heuristic evaluation data, ML governance tables, backtest runs, and the immutable `decision_audit` ledger.

Redis is used for real-time state, pub/sub, idempotency, leases and shared risk runtime state. It is not the durable source of truth for orders/fills/decision history.

## Testing

The repository now contains a broad focused regression suite rather than the old “145 tests across 7 files” snapshot. Current test modules cover, among other areas:

- execution safety and PositionLedger accounting;
- durable order lifecycle and conditional orders;
- runtime and Redis reliability;
- historical event-time backtesting;
- frontend/backend alignment;
- heuristic performance;
- ingestion provenance and state contracts;
- ML governance and audit/governance correctness;
- decision audit, final decision boundary, operator authorization, production readiness and counterfactual replay;
- equities, institutional intelligence and geopolitical intelligence.

Run the repository test suite with:

```bash
pytest -q
```

Use `pytest --collect-only -q` when an exact current test count is needed; this README intentionally avoids freezing another stale test-count snapshot.

## External Dependencies

- **PostgreSQL / psycopg2** — durable storage and migrations.
- **Redis** — real-time state, pub/sub, idempotency, leases and shared runtime coordination.
- **FastAPI / Uvicorn** — API/application server.
- **APScheduler** — scheduled ingestion.
- **Pyth Network, Kraken, CoinGecko** — crypto price authority/fallback sources.
- **Hyperliquid, Drift** — market data and prototype live-execution integrations.
- **Jupiter / Solana RPC** — Solana quote/swap research integration; direct execution remains explicitly gated and prototype-only.
- **World Bank WITS / GDELT** — tariff and news/macro inputs.
- **yfinance / Stooq** — research-grade equity sources with fail-open behavior.
- **scikit-learn** — governed ML training/inference path.
- **Chart.js** — frontend charting.
- **pytest** — tests.

## Historical Product Expansions

The earlier **Equity + Execution Safety Expansion**, **Institutional Intelligence Layer**, and **Geopolitical Risk Intelligence Layer** remain part of the current codebase. Their core product intent is unchanged: expand the desk's research breadth while preserving deterministic/proposal-only behavior, graceful provider degradation, paper-first execution and explicit live-trading safety gates.

For a more detailed file-by-file map, see `codebase.md`. For a plain-English product walkthrough, see `Summary.md`. For chronological development history, see `changelog.md`.
