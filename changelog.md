# Changelog

## 2026-08-17 — Counterfactual Decision Replay (PR #24)

### Added
- Added `backend/compute/counterfactual_replay.py` as a research-only transformation layer over the existing exact replay engine.
- Counterfactual analysis now requires the immutable baseline decision to reproduce exactly before any what-if scenario is evaluated.
- Added semantic scenario overrides for relevant macro/model/allocation/execution/risk inputs such as shock score, volatility regime, stablecoin health, spread, liquidity depth, fill price, order size, historical daily P&L, and throttle state where those components actually existed in the historical decision.
- Preserved component truthfulness: a component recorded as `not_used` is never silently activated by a counterfactual.
- Locked historical component identities such as heuristic version, ML model/version/artifact SHA, decision timestamp, execution-decision version, and risk-policy limits.
- Added `POST /api/decisions/{decision_id}/counterfactual` as a read-only research calculation endpoint.
- Added an additive Decision Audit UI for entering scenario values and comparing original vs counterfactual final decisions.
- Added focused tests for deterministic reruns, baseline exactness, immutable original records, `not_used` preservation, invalid scenario rejection, read-only auth classification, and the no-execution/no-persistence boundary.

### Safety
- Counterfactual replay writes no decision row, reads no current live Redis state, retrains no model, changes no policy/version identity, and submits zero orders.
- The endpoint remains outside the operator mutation allowlist because it performs no state-changing action.

---

## 2026-08-17 — Production Readiness / Liveness Separation (PR #23)

### Added
- Added root-level `GET /live` and `GET /ready`, plus `/api/health/live` and `/api/health/ready` equivalents.
- Added `backend/core/readiness.py` to aggregate existing PostgreSQL, schema, Redis, market-data, ingestion, risk, operator-auth, and execution-configuration contracts.
- Added a small required-table check for critical live execution/audit tables: `order_intents`, `orders`, `fills`, `positions`, and `decision_audit`.
- Market readiness now requires a real provider timestamp, freshness within the existing configured threshold, and truthful price-integrity state.
- Live readiness validates Redis/shared-risk availability, configured risk-policy sanity, operator-token configuration, execution flags, supported live venues/markets, and production-ready executor availability.
- Research ingestion degradation remains visible but non-blocking for live execution readiness where the feed is not an execution prerequisite.

### Mode Semantics
- **Paper/research:** critical provider/storage outages can surface as degraded while the application remains available for research where safe.
- **Live-capable:** missing PostgreSQL/schema, Redis/shared risk, fresh/integrity-OK market data, valid risk runtime, operator auth, or production-ready execution configuration causes `NOT READY` / HTTP 503.
- Current Hyperliquid and Drift live executors remain prototype-only, so readiness truthfully does not claim production live-execution readiness today.

### Scope
- No GitHub Actions, YAML/YML workflows, Prometheus, Grafana, OpenTelemetry, Kubernetes, migration framework, or second observability stack was added.

---

## 2026-08-17 — Operator Authorization + Live Surface Hardening (PR #22)

### Added
- Added `backend/core/operator_auth.py` with environment-backed Bearer token validation using constant-time comparison.
- Added `OPERATOR_API_TOKEN` and `OPERATOR_AUTH_REQUIRED` configuration.
- Any live-capable configuration (`EXECUTION_MODE=live` or `LIVE_EXECUTION_ENABLED=true`) now forces operator authorization even if the explicit paper/research flag is false.
- Protected true state-changing surfaces including primary order submission, conditional/smart-order mutations, ML offline training/promote/rollback, manual decision creation, persisted heuristic evaluation, backtest execution, watchlist mutations, and direct Jupiter swap execution.
- Left read-only/research calculations such as exact replay, scenarios, stress/allocation previews, and later counterfactual replay outside the mutation boundary.
- Added a small frontend operator-access control using `sessionStorage`; bearer credentials are attached only to protected mutation requests.

### Jupiter Hardening
- Added `ENABLE_DIRECT_JUPITER_SWAP=false` as an independent default-off gate for the direct Jupiter spot-swap endpoint.
- Kept the existing Jupiter/Solana adapter explicitly prototype-only rather than forcing spot-swap semantics through the perp-oriented `ExecutionRouter`.
- Missing/invalid operator credentials fail closed when auth is required; configured secrets are never returned in configuration summaries.

---

## 2026-08-17 — Final Decision Boundary + Audit Completion (PR #21)

### Added / Fixed
- Added `backend/compute/execution_decision.py`, a pure deterministic final pre-trade ALLOW/BLOCK combiner.
- Exact replay now recomputes the final execution decision from the newly recomputed data/risk/execution-agent components instead of copying stored `final_decision` input.
- Preserved the existing immutable `execution_admission` row as an admission-intent record.
- Added a second immutable `execution_pre_trade_final` decision record after real data/risk/execution-agent checks and before any allowed paper/live submission.
- Linked the final record back to the admission record with `admission_decision_id` instead of making audit rows mutable.
- Final audit records capture deterministic data guardrails, historical/shared risk inputs, execution-agent inputs/results, configuration limits and the final decision.
- API-linked live new exposure cannot proceed when the final audit record cannot be persisted; confirmed pure reductions retain the narrowly scoped degraded-mode escape from the risk-safety layer.
- Normalized ML validation and heuristic evaluation timestamps to canonical UTC so equivalent `Z` and `+00:00` timestamps align correctly.

---

## 2026-08-11 — Audit Replay & Governance Correctness (PR #20)

### Fixed
- Reworked historical decision replay so heuristic, ML, risk and allocation components are genuinely recomputed from explicit stored replay inputs rather than merely re-hashing stored outputs.
- Exact heuristic replay now requires the requested registered rule/version.
- Exact ML replay verifies the historical model/version/artifact SHA and deserializes the recorded artifact; it never silently substitutes the current active model.
- Historical risk replay uses an inert runtime so it does not read or mutate current Redis/shared live state.
- Allocator and risk clocks use the historical decision timestamp for deterministic replay.
- Legacy/incomplete records now return `UNAVAILABLE` rather than pretending to reproduce exactly.
- ML promotion/rollback became transactional so active-model lifecycle transitions are atomic.
- Training method handling became explicit/truthful and validation records are durably represented in training metrics.
- ML training history now prefers durable PostgreSQL history, with clearly labeled process fallback when necessary.
- Removed fabricated strategy/signal performance fallbacks: missing realized outcomes remain unavailable/unevaluated instead of being synthesized.

### Validation recorded in PR
- Targeted audit/governance tests reported 12 passed and 4 skipped in the PR environment.
- Python compile checks and frontend Node syntax checks for the touched modules succeeded.
- A full suite was not claimed because the PR environment lacked several dependencies.

---

## 2026-08-11 — Execution / Risk Safety Unification (PR #19)

### Added / Fixed
- Added a shared configured risk-policy boundary so RiskEngine instances use the same environment-defined leverage, margin, daily-loss and cooldown settings by default.
- Moved throttle, daily realized P&L and live cooldown runtime state onto the existing Redis-backed shared risk runtime when Redis is available.
- Paper fills feed realized P&L back into shared daily risk state.
- Live new exposure through `POST /api/execution/order` now requires a confirmed Redis idempotency claim and durable order-intent persistence before routing.
- If those critical live new-exposure prerequisites are unavailable, the request fails closed before venue routing.
- Confirmed pure reductions preserve degraded-mode escape behavior so infrastructure degradation does not unnecessarily trap risk.
- Added finite-number validation for execution and risk inputs to reject NaN/Infinity values.

---

## 2026-08-11 — Canonical State & Data Contract Hardening (PR #18)

### Added / Fixed
- Added `backend/core/state_keys.py` as a central contract for canonical price aliases, WITS, GDELT, stablecoin, prediction and price-integrity snapshots.
- Pyth, Kraken and CoinGecko continue publishing provider-native keys while also exposing canonical normalized aliases.
- `PriceAuthority` and market-integrity consumers use canonical-first lookup with explicit compatibility fallbacks.
- Price integrity now reports `UNKNOWN` when fewer than two valid sources exist; `OK` is reserved for actual cross-source validation.
- Added configurable Pyth Hermes endpoint/API-key support without exposing the secret.
- Hardened WITS aggregate output and kept compatibility publishing to the legacy key.
- Stablecoin-health and prediction producers/readers gained canonical + compatibility contracts so ML/allocation/volatility consumers read the actual data shapes truthfully.

---

## 2026-08-11 — Decision Audit Ledger + Exact Replay (PR #17)

### Added
- Added the immutable `decision_audit` PostgreSQL table and `DecisionRepository` create/get/list boundary.
- Added canonical decision normalization, SHA-256 decision hashing, structured diffs and read-only replay semantics.
- Added `POST /api/decisions`, `GET /api/decisions`, `GET /api/decisions/{decision_id}` and `POST /api/decisions/{decision_id}/replay`.
- Added the Decision Audit frontend tab with durable decision detail and research/audit-only replay results.
- Added decision-record/replay/mismatch event types.
- Replay was deliberately isolated from execution submission paths.

### Follow-up
- PR #20 made component replay genuinely recomputational.
- PR #21 completed deterministic final-decision recomputation and the true final pre-trade immutable audit boundary.

---

## 2026-08-11 — ML Reliability & Model Governance (PR #16)

### Added
- Added feature schema/version metadata and per-feature provenance (`observed`, `derived`, `fallback`, `default`).
- Added deterministic dataset manifests and SHA-256 identity with strict temporal ordering and versioned label definitions.
- Reworked training to use a leak-resistant sklearn pipeline with temporal walk-forward validation.
- Added durable ML datasets, training runs, immutable model versions and prediction records in PostgreSQL.
- Added artifact serialization/SHA verification, candidate eligibility, explicit promote/rollback and model-health logic.
- Inference now loads the durable active model, verifies artifact/schema compatibility, records prediction provenance/input hashes and falls back explicitly when required.
- Added model registry/dataset/training/model-health/comparison APIs and frontend governance visibility.
- Model training remains offline/candidate-oriented; there is no automatic promotion or automatic trading link.

---

## 2026-08-11 — Ingestion Provenance Correctness Follow-up (PR #15)

### Fixed
- Standardized WITS freshness identity on the canonical `wits:tariff:aggregate` snapshot while preserving per-country/product data.
- Corrected GDELT processed-vs-persisted accounting so aggregate persistence is not represented as raw-article persistence.
- Restored Hyperliquid market snapshots to the read-only Source Registry without pretending they are scheduled durable ingest runs.
- Expanded provenance regression coverage for source IDs, lease behavior, Drift split market/funding identities and frontend provenance wiring.

---

## 2026-08-11 — Ingestion Registry + Data Provenance (PR #14)

### Added
- Added a code-defined Source Registry for stable provider identities, cadence, storage targets and fallback chains.
- Added `IngestRunContext`, durable `ingest_runs` and `data_provenance` ledgers, and `ingest_repo.py`.
- Wrapped existing APScheduler lifecycle with run start/finish/failure recording while preserving Redis leases and fail-soft provider behavior.
- Added optional provenance hooks to market/index persistence.
- Added read-only `/api/ingestion/registry`, `/status`, `/runs` and `/provenance` APIs plus frontend Source Registry / Ingestion Health / Provenance Inspector surfaces.

---

## 2026-08-11 — Historical Heuristic Performance Lab (PR #13)

### Added
- Added stable heuristic IDs/versions and evaluation metadata while preserving existing deterministic rule conditions.
- Added `heuristic_performance.py` for event-time context reconstruction, horizon outcome matching, directional/risk-control metrics, regime segmentation and decay analysis.
- Added durable `heuristic_evaluations` persistence with idempotent upserts.
- Added `/api/heuristics/registry`, `POST /evaluate`, `/performance` and `/evaluations`.
- Added the Heuristic Performance Lab inside the existing Strategy tab and explicitly avoided synthetic historical fallback.

---

## 2026-08-11 — Core Frontend Integration of Backend Hardening (PR #12)

### Changed
- Moved the temporary compatibility behavior from PR #11 directly into the authoritative vanilla-JS frontend files.
- Added explicit Synthetic Research vs Historical Event-Time Backtest Lab controls, historical coverage/history views and advanced historical configuration.
- Added execution safety metadata, order type/slippage controls, durable lifecycle visibility, PositionLedger accounting views, Redis telemetry and portfolio-risk detail to the native frontend.
- Reduced `frontend_alignment.js` to a harmless compatibility stub.
- Preserved the existing frontend architecture rather than introducing React or another framework.

---

## 2026-08-11 — Frontend / Backend Alignment Layer (PR #11)

### Added
- Added an additive compatibility layer after PRs #5–#10 so the browser could expose historical-backtest v2 controls, execution safety, lifecycle state, PositionLedger accounting, Redis telemetry and portfolio risk without rewriting the large core UI in that PR.
- Clarified Synthetic Research vs Historical Event-Time behavior and surfaced server-provided live-execution guardrails/readiness metadata.

### Follow-up
- PR #12 migrated this behavior into the core frontend and reduced the compatibility script to a no-op stub.

---

## 2026-08-10 — Historical Event-Time Backtester v2 (PR #10)

### Added
- Upgraded the backtester from synthetic-only research simulation to explicit `synthetic` and `historical` modes.
- Historical mode consumes persisted `market_ticks`, `funding_ticks`, `index_history`, `stablecoin_ticks`, `regime_snapshots`, `events`, `orders` and `fills` where available.
- Added deterministic event-time sorting and look-ahead protection; simulated orders are not eligible to fill before their configured latency point.
- Reused PositionLedger for opens/reductions/flips, realized/unrealized P&L, fees, signed funding and slippage.
- Added latency, maker/taker fees, signed funding, slippage, full/fixed-partial fill assumptions, capital constraints and optional walk-forward windows.
- Historical mode has no automatic synthetic fallback when requested data is unavailable.
- Added persistence hooks so supported market/funding ingestors append historical observations while preserving Redis snapshots.
- Added durable `backtest_runs` metadata and coverage/run-detail APIs.

---

## 2026-08-10 — Shared Redis Runtime & Distributed Coordination (PR #9)

### Added / Changed
- Added `backend/core/redis_runtime.py` as the shared process-level sync/async Redis pool boundary.
- Added bounded connection settings, health/recovery counters, optional key prefixing, publish/pubsub helpers and graceful shutdown.
- Added explicit idempotency claim status (`claimed`, `duplicate`, `unavailable`) with debugging metadata and backward compatibility for legacy keys.
- Added TTL-bound Redis leases with owner-safe release and applied them to scheduled ingest jobs.
- Hardened WebSocket pub/sub reconnect/cleanup behavior through the shared runtime.
- Expanded `/api/health/redis` with runtime telemetry.
- PostgreSQL remains durable source of truth; Redis remains realtime state/coordination.

---

## 2026-08-10 — Runtime Resource Reliability (PR #8)

### Changed
- Removed application-owned `redis-server` subprocess startup; Redis is now an external service configured through `REDIS_URL`.
- Replaced `SimpleConnectionPool` with psycopg2 `ThreadedConnectionPool` while preserving public DB helper APIs.
- Added migration advisory locking so multiple workers do not apply `migrations.sql` concurrently.
- Added idempotent PostgreSQL pool shutdown and ensured scheduler/DB cleanup runs through FastAPI lifespan finalization.
- No Docker/Kubernetes/Alembic/SQLAlchemy/asyncpg platform was introduced.

---

## 2026-08-10 — Durable Order Lifecycle + Conditional Persistence (PR #7)

### Added
- Added `orders_repo.py` owning order intents, normalized orders, order events, fills, paper orders and conditional-order transitions.
- Added normalized tables including `order_intents`, `orders`, `order_events`, `fills` and `paper_orders`, while keeping legacy paper history readable for compatibility.
- Added explicit lifecycle states/events for risk approval, submission, acknowledgement, open/partial fill, cancellation, rejection and submission-unknown/reconciliation conditions.
- Removed process-local conditional orders as source of truth; conditional orders are persisted in PostgreSQL with parent/child/OCO/trigger state.
- Trigger claims use an atomic update/returning boundary to avoid duplicate worker execution.
- Submitted/acknowledged venue responses are not automatically persisted as fills.

---

## 2026-08-10 — PositionLedger + Portfolio Risk (PR #6)

### Added / Fixed
- Added reusable `backend/core/position_ledger.py` and delegated paper position accounting to it.
- Corrected partial reductions, full closes and long/short flips while preserving average entry where appropriate.
- Added explicit realized/unrealized P&L, fees, funding and slippage accounting.
- Added a portfolio/account snapshot schema with cash, collateral, realized/unrealized P&L, margin, gross/net exposure, open-order exposure, buying power and exposure breakdowns.
- RiskEngine can calculate leverage, margin utilization, concentration and liquidation-buffer metrics from account equity while retaining backward-compatible position-only calls.
- Strengthened execution validation for supported venues/markets/order types, finite positive size/price, max notional and slippage.

---

## 2026-08-10 — Execution & Risk Safety Boundary Hardening (PR #5)

### Added / Fixed
- Added `LIVE_EXECUTION_ENABLED=false` as a second independent live-execution gate.
- Kept Hyperliquid, Drift and Jupiter execution adapters explicitly prototype-only until proper production signing/reconciliation paths exist.
- Removed unsafe unknown-market fallbacks and stopped prototype adapters from representing unsupported/unsigned behavior as successful execution.
- Changed live pre-trade risk inputs to observable live positions rather than paper-only positions.
- Corrected reduce-to-flip handling so only the actually reducing portion receives risk-reduction bypass behavior.
- Removed fake paper fills after uncertain live submission; uncertain states now require reconciliation.
- Added request/client/strategy/decision/idempotency identifiers and execution-intent auditing.
- Standardized event IDs and migration authority.

---

## 2026-06-11 — Geopolitical Risk Intelligence Layer

- Added fail-open geopolitical compute modules for sanctions pressure, conflict escalation, shipping/chokepoint risk, energy/commodity shock, market impact, geopolitical risk indexing, and portfolio protection proposals.
- Added proposal-only geopolitical agents for geopolitical risk, sanctions, conflict, energy shock, and protection posture; these emit deterministic explainable signals and do not trade.
- Added `/api/geopolitical/*` endpoints for index, events, sanctions, conflicts, chokepoints, shipping risk, energy shock, commodity impact, market impact, scenario templates/runs, agent signals, and geopolitical reports.
- Added `/api/protection/status` and `/api/protection/preview` for portfolio protection status and previews.
- Added the vanilla JS **Geopolitics** tab with risk index, component/regional panels, events, sanctions, conflict, shipping, energy, market impact, scenario, protection, agent, and report panels.
- Added tests for compute engines, agent signal shapes, endpoint response shapes, fail-open payloads, scenario output, protection output, and no-autonomous-trading assertions.
- Safety: geopolitical/sanctions outputs remain research/development only, informational/proposal-only, not legal/financial/investment advice, and degraded/fallback data is clearly marked.

---

## 2026-06-10 — Institutional Intelligence Audit Fixes

### Fixed
- Verified institutional routers and endpoint shapes with tests that assert new routes are registered once and requested endpoints return safe JSON.
- Hardened new UI renderers against null inputs and fixed report copy-button payload handling.
- Fixed zero-volatility positive-return Sharpe handling in the backtester so deterministic positive return streams produce a positive Sharpe.
- Added explicit fail-open tests for missing Stooq, WITS/GDELT, Redis, Postgres, and empty datasets.

### Verification
- Full pytest suite was reported passing in the project virtual environment at that point in repository history.

---

## 2026-06-10 — Institutional Intelligence Layer

### Added
- Macro event calendar and market impact tracker endpoints under `/api/macro/*`.
- Tariff beta / macro sensitivity compute module and `/api/macro-sensitivity/*` endpoints.
- Cross-asset correlation and contagion map under `/api/cross-asset/*`.
- Scenario builder templates and proposal-only scenario run endpoint.
- Cross-asset hedge recommendations extending existing hedge routes.
- Portfolio explainability endpoints for portfolio and recommendation-level explanations.
- Agent consensus endpoint plus signal outcomes and attribution endpoints.
- Watchlist builder endpoints with in-memory fallback.
- Institutional report generator endpoints for daily brief, tariff risk, portfolio risk, and agent signals.
- Frontend panels for macro events, sensitivity, correlations/contagion, scenario builder, hedges, explainability, consensus, attribution, watchlists, and reports.
- Tests for new compute modules, safe output shapes, endpoint fail-open behavior, and frontend-safe responses.

### Safety
- All new intelligence is deterministic, heuristic, explainable, and proposal-only.
- Missing APIs/providers/databases return degraded JSON with safe defaults.
- Paper mode remains default and live trading behavior is unchanged.

---

## 2026-06-10 — Equity Market + Execution Safety Expansion

### Added
- Equity ingestion modules for yfinance and Stooq with deterministic mock/demo fallback data.
- Equity analytics for returns, volatility, drawdown, moving averages, RSI, beta proxy, relative strength, volume spike, sectors, provider status, and timestamps.
- Equity tariff exposure scoring aligned with WITS/GDELT where available and safe defaults when unavailable.
- Equity risk, tariff exposure, and sector rotation heuristic agents.
- `/api/equities/overview`, `/api/equities/quote/{ticker}`, `/api/equities/history/{ticker}`, `/api/equities/watchlist`, `/api/equities/risk`, `/api/equities/tariff-exposure`, `/api/equities/sector-rotation`, and `/api/equities/cross-asset`.
- `/api/allocation/execution-preview` for proposal-only pre-trade sizing checks.
- Paper-mode conditional order endpoints for stop loss, take profit, trailing stop, bracket orders, evaluation, listing, and cancellation.
- Paper-mode TWAP/VWAP smart order endpoints with slice schedules and slippage estimates.
- `/api/strategy/performance`, `/api/health/data-quality`, `/api/replay/trade-simulation`, `/api/agents/performance`, and `/api/agents/history`.
- New Equities frontend tab and additive Strategy, Execution, Risk, and Agents panels.
- Tests covering equity provider fallback, analytics, tariff exposure scoring, endpoint fail-open behavior, agent signal structure, and allocation execution preview.

### Safety
- Paper mode remains default.
- No autonomous live trading was added.
- Equity providers fail open to degraded status and demo fallback data.
- Existing endpoints, tabs, functions, files, and CSS classes were preserved.

---

## 2026-02-25 — Fix Paper SELL + Live Pricing + Clean Logs

### Root Cause
Paper SELL was blocked by the risk engine's **300-second cooldown timer**. After any successful order (BUY), all subsequent orders — including sells — were rejected with "Cooldown active: Xs remaining" for 5 minutes. The cooldown was designed for live trading safety but incorrectly applied to paper mode.

## Files Changed

| File | Change |
|------|--------|
| `backend/compute/risk_engine.py` | Added `_is_reducing()` method to detect position-reducing trades. Cooldown now only enforced in live mode. Throttle, leverage, margin, and daily loss checks bypass for position-reducing trades (sells that close/reduce existing longs, buys that close/reduce shorts). Added `execution_mode` parameter to `check_constraints()`. |
| `backend/execution/router.py` | Added live price injection via `PriceAuthority` — orders without explicit price now auto-fill from the Pyth→Kraken→CoinGecko cascade. Added price freshness validation (configurable threshold, default 30s). Stale data blocks live trades, allows paper trades with DEGRADED tag. Integrity WARNING blocks live trades (configurable), tags paper trades. Added `TRADE_BLOCKED_STALE_DATA` and `TRADE_DEGRADED_DATA` event emissions. |
| `backend/execution/paper_exec.py` | Position data now includes `side` field ("long"/"short" derived from signed size). ORDER_SENT and ORDER_FILLED events now include `price_source`, `price_asof_ts`, `data_quality`, and human-readable `message` fields. Return value now includes `side`, `market`, `venue`, `size`. |
| `backend/api/execution_routes.py` | Added explicit side validation (must be "buy" or "sell", returns 400 otherwise). Better error response structure with `status` and `message` fields. |
| `backend/core/event_bus.py` | Added event types for blocked/degraded stale-data execution outcomes. |
| `backend/config.py` | Added `PRICE_FRESHNESS_THRESHOLD_S` and `PRICE_INTEGRITY_BLOCK_LIVE` configuration. |
| `backend/logging_config.py` | APScheduler loggers set to WARNING level to eliminate noisy scheduler-job messages during trading. |
| `frontend/assets/api.js` | Improved structured execution error parsing and downgraded expected API failures from browser `console.error` to `console.warn`. |
| `tests/test_risk_throttle.py` | Updated cooldown coverage for live vs paper behavior and risk-reduction bypass. |
| `tests/test_paper_trading.py` | Added paper BUY/SELL/open/reduce/close/flip and risk-reduction behavior coverage. |

## How Live Pricing Freshness/Integrity Is Enforced

Before every trade:
1. The router fetches the latest price from the authority cascade (Pyth → Kraken → CoinGecko).
2. If no price data exists and no explicit price was provided, the trade is blocked.
3. Price freshness is checked against `PRICE_FRESHNESS_THRESHOLD_S`.
4. Price integrity is considered before live submission; paper mode can surface degraded data while allowing research behavior where configured.
5. Trade/audit context carries price/source/data-quality timing fields.

### Paper SELL Behavior Rules
- `side: "sell"` opens a short position if no existing position.
- `side: "sell"` reduces/closes an existing long position.
- An oversized sell can flip long → short.
- Symmetric behavior applies to buys against shorts.
- Pure reducing/closing trades retain special safety treatment so positions can be exited even while new exposure is constrained.

### Historical Test Snapshot
At this point in the project's history, the changelog recorded a 98-test passing snapshot. The repository has expanded substantially since then; use `pytest --collect-only -q` for the current test count rather than treating this historical number as current.
