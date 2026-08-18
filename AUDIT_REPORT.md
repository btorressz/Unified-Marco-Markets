# Unified Macro Markets — Repository Audit Report

**Audit date:** 2026-08-18  
**Scope:** current checked-out `work` branch; 227 application, test, and documentation files inventoried, with all 199 Python/HTML/CSS/JavaScript/SQL/Markdown files reviewed by structure/search and the principal runtime paths read in detail. Code is authoritative below.  
**Finding count:** 0 critical, 3 high, 11 medium, 6 low, 4 informational.

## 1. Executive Summary

Unified Macro Markets is a broad, coherent **research-first monolith** with unusually strong deterministic execution admission, immutable decision evidence, exact replay, counterfactual safety, durable order accounting, and explicit degraded states. FastAPI routes orchestrate providers, deterministic compute modules, PostgreSQL repositories, Redis snapshots/coordination, and a vanilla browser research desk (`main.py:create_app`). The design remains understandable after many additions, but breadth now exceeds data depth in several places.

Research readiness is **strong for decision/execution-method research, moderate for market history, and weak-to-moderate for tariff and geopolitical inference**. Three high findings dominate: WITS results lose their dimensions and failed requests inject sample rows into an aggregate as though they were observations; geopolitical endpoints turn a small aggregate news snapshot plus static maps/defaults into specific sanctions, conflict, shipping and commodity claims; and stablecoin routes silently substitute exactly 1.0 when feeds are absent. These are truthfulness defects, not reasons to rewrite the platform.

Largest strengths are: (1) deterministic final ALLOW/BLOCK recomputation, (2) immutable admission/final-decision separation, (3) research/execution price-tier separation, (4) read-only exact/counterfactual replay, and (5) event-time backtesting with explicit costs and manifests. Largest gaps are source-specific historical persistence, complete lineage from derived values to source artifacts, statistically cautious performance summaries, authoritative geopolitical inputs, and consistent browser freshness/provenance presentation.

The repository still feels coherent. The provider → state → compute → API layering is sound. The main architectural pressure is a long tail of sidecar analytics and 47 route modules, many of which expose deterministic demonstrations rather than empirically grounded research. Preserve the monolith, repositories, pure compute functions, and simple frontend; deepen evidence before adding breadth.

## 2. Current Architecture

```text
WITS / GDELT / Pyth / Kraken / CoinGecko / Drift / Yahoo / Stooq
          | scheduled ingest (leases + ingest-run context)
          v
 normalization + source registry + provenance
          |                    |
          v                    v
 Redis snapshots/TTL     PostgreSQL observations and ledgers
          \                    /
           v                  v
 deterministic compute: tariff/index, regimes, market/risk, agents, ML fallback
                         |
                         v
 admission audit -> data guardrails -> portfolio risk -> execution agent
                         |
                         v
 deterministic final decision -> immutable final audit -> paper/gated adapter
                         |                                  |
                         v                                  v
 exact replay / outcomes / cohorts / counterfactuals   orders/fills/positions
                         \                                  /
                          v                                v
                    FastAPI research APIs -> vanilla JS/Chart.js desk
```

`backend/ingest/scheduler.py:IngestScheduler` schedules seven polling families and uses a Redis lease when available. `backend/core/state_store.py:StateStore` is the runtime abstraction; `backend/data/repositories/` holds durable access. Compute is generally separated from I/O. `backend/api/execution_routes.py` is an exception: at 784 lines it owns substantial admission orchestration, conditional evaluation, idempotency and audit assembly. Historical replay stays isolated from execution imports (`backend/compute/decision_replay.py`, `counterfactual_replay.py`).

Runtime and durable state have purposeful roles, but not every source reaches durable history. Canonical keys and explicit compatibility aliases are centralized in `backend/core/state_keys.py`; retaining them temporarily is reasonable, but retirement telemetry is absent. Health is split among readiness, feed status, ingest status, provenance, Redis health and data-quality responses; these serve different questions but lack one shared response vocabulary.

## 3. Current Capability Inventory

| Capability | Status | Key Files | Data Sources | Research Value | Main Gap |
|---|---|---|---|---|---|
| Tariff ingestion/index | IMPLEMENTED WITH GAPS | `wits_ingest.py`, `index_calc.py`, `index_routes.py` | WITS | High | dimensions/history and fallback contamination |
| News shock | IMPLEMENTED WITH GAPS | `gdelt_ingest.py`, `shock_calc.py` | GDELT DOC | Medium | aggregate only; no article/event history |
| Geopolitical intelligence | PROTOTYPE | `geopolitical_routes.py`, `geopolitical_risk.py` | GDELT/WITS/default maps | High potential | specific claims exceed evidence |
| Execution-grade price selection | IMPLEMENTED | `price_authority.py`, `price_validator.py` | Pyth/Kraken/CoinGecko | High | first-source rather than quorum/median; SOL-centric |
| Research prices/equities | IMPLEMENTED WITH GAPS | `yfinance_ingest.py`, `stooq_ingest.py`, `equities_routes.py` | Yahoo/Stooq | High | demo fallback and provider fragility |
| Funding/derivatives | PARTIAL | `drift_ingest.py`, `hyperliquid_ws.py`, `basis_engine.py` | Drift/Hyperliquid | Medium | venue units/history not fully unified |
| Stablecoin health | PARTIAL | `stablecoin_health.py`, `stablecoin_routes.py` | intended Pyth/Kraken | Medium | missing prices become 1.0; weak history |
| Position/risk accounting | IMPLEMENTED | `position_ledger.py`, `risk_engine.py`, repositories | orders/fills/positions | High | scenario exposure more useful than more limits |
| Durable order lifecycle | IMPLEMENTED | `orders_repo.py`, `execution/router.py` | venue adapters/paper | High | live reconciliation adapters remain prototypes |
| Decision audit/final boundary | IMPLEMENTED | `decision_repo.py`, `execution_decision.py` | recorded state | Very high | provenance frequently partial |
| Outcomes/performance lab | IMPLEMENTED WITH GAPS | `decision_outcomes.py`, `decision_outcome_repo.py` | market ticks | Very high | sample uncertainty and query cost |
| Regime/cohort analytics | IMPLEMENTED WITH GAPS | `decision_outcomes.py` | regimes/index/stable ticks | High | context age and sparse cohorts |
| Exact replay | IMPLEMENTED | `decision_replay.py`, `decision_evaluator.py` | immutable record/artifacts | Very high | old/partial records may be unavailable |
| Counterfactual/boundaries | IMPLEMENTED | `counterfactual_replay.py`, `counterfactual_sensitivity.py` | replay inputs/outcomes | Very high | units, baseline presets, boundary distance |
| Historical backtester | IMPLEMENTED WITH GAPS | `backtester.py`, `backtest_repo.py` | seven durable streams | High | source coverage and manifests lack source versions |
| Heuristic evaluation | IMPLEMENTED WITH GAPS | `rules_engine.py`, `heuristic_performance.py` | recorded observations | High | thresholds spread across modules |
| Governed ML | IMPLEMENTED WITH GAPS | `ml/` | supplied datasets/features | Medium | fallback is more active than trained ML |
| Frontend research desk | IMPLEMENTED WITH GAPS | `frontend/index.html`, `assets/` | API families | High | provenance/freshness/uncertainty inconsistent |

## 4. Major Strengths

1. **Final decision integrity.** `backend/execution/router.py:submit` creates a distinct `execution_pre_trade_final` record before permitted submission and links it to admission evidence. `backend/compute/execution_decision.py` is pure and reused by replay.
2. **Counterfactual isolation.** `prepare_counterfactual`, `evaluate_prepared_counterfactual`, and `counterfactual_sensitivity` deep-copy records, require an exact baseline, apply an allowlist, report zero orders, and do not import execution/runtime state.
3. **Price trust tiers.** `PriceAuthority.get_price` excludes Yahoo by default, while `PriceValidator.validate` requires two execution-grade sources and labels Yahoo corroboration ineligible.
4. **Durable execution research.** The SQL ledger separates intents, orders, events and fills; `PositionLedger` accounts for fees, funding, slippage and realized/unrealized P&L.
5. **Historical event semantics.** `backtester.py` sorts heterogeneous observations, delays fills beyond the decision tick, separates synthetic/historical modes, and reports fees, slippage, funding and a data manifest.
6. **Governed ML degradation.** Artifacts are hashed, schemas/version ordering are explicit, promotion is manual, temporal folds are checked, and missing/bad artifacts fall back visibly (`backend/ml/governance.py`, `inference.py`).
7. **Pragmatic infrastructure.** PostgreSQL and Redis remain appropriately scoped; Redis unavailability degrades research while new live exposure fails closed where coordination is required.

## 5. Critical / High Priority Findings

No critical finding was substantiated.

### [DATA-01] WITS fallback and dimensional parsing can produce a misleading tariff aggregate

**Severity:** HIGH  
**Area:** Data Ingestion / Tariff  
**Evidence:** `backend/ingest/wits_ingest.py:fetch_tariff_data` returns `_SAMPLE_TARIFF_DATA` on empty/error; `_parse_response` retains only observation key and rate; `_store_aggregate_freshness` averages all returned rates, including sample rows, and timestamps the aggregate now. `fetch_all` passes configured values such as `USA`, `CHN`, `EU`, `Capital` directly into an SDMX key whose defaults are numeric codes. Per-query snapshots are only written on provider success.  
**Why it matters:** A provider outage or invalid dimension can yield a plausible, current-looking pressure value assembled from unrelated 2025 samples. Country/product/year/trade weights cannot be audited or replayed.  
**Recommended action:** Never include samples in the canonical provider aggregate; validate/map SDMX dimensions; parse series metadata/time dimensions; label samples as synthetic artifacts; persist normalized tariff observations and raw-response hashes.  
**Scope:** Medium  
**Priority:** Now

### [GEO-01] Specific geopolitical claims are generated from aggregate news and static defaults

**Severity:** HIGH  
**Area:** Geopolitical Intelligence  
**Evidence:** `gdelt_ingest.py:_store_results` stores only article count, shock score and timestamp, while downstream modules look for tone not present. `sanctions_risk.py` uses static programs/demo entities and an optional OFAC argument never supplied by `geopolitical_routes.py:sanctions_entity_feed`. `shipping_energy_risk.py` assigns risk to every hard-coded chokepoint from the same global shock/tone proxy. `geopolitical_market_impact.py` maps the same overall score deterministically to every asset.  
**Why it matters:** Outputs are explainable as formulas but not evidence-backed at entity, region, chokepoint or commodity level. Users can mistake a scenario template/proxy for observed sanctions or disruption intelligence.  
**Recommended action:** Make current outputs explicitly `proxy/scenario`; persist normalized source articles/events; add authoritative sanctions and event sources before entity/change claims; require region/entity evidence for specific endpoints.  
**Scope:** Large  
**Priority:** Now

### [STABLE-01] Missing stablecoin prices silently become perfect pegs

**Severity:** HIGH  
**Area:** Stablecoin / Data Quality  
**Evidence:** `backend/api/stablecoin_routes.py:_get_stable_prices` substitutes `1.0` after two noncanonical key lookups. `get_latest` saves that computed health, while `StablecoinHealthMonitor` cannot distinguish observed from substituted prices.  
**Why it matters:** Missing feeds become healthy observations, can enter runtime state, suppress alerts, and contaminate allocation, cohorts, and research history.  
**Recommended action:** Represent unavailable prices as unavailable; attach source/as-of/quality; only persist observed ticks; make consumers handle missing health explicitly.  
**Scope:** Small  
**Priority:** Now

## 6. Medium Priority Findings

### [PROV-01] Derived-value lineage stops at aggregate snapshots
**Severity:** MEDIUM  
**Area:** Provenance  
**Evidence:** `source_registry.py` and `ingest_runs/data_provenance` record source/run artifacts, but GDELT stores one aggregate and WITS advertises a Redis target; geopolitical, tariff index, funding-regime and stable-health outputs do not consistently emit source IDs, artifact IDs, as-of age and transformation version. Decision creation explicitly marks records without references `partial`.  
**Why it matters:** “Where did this number come from?” is answerable for some ingest and decisions, not end-to-end for major scores.  
**Recommended action:** Adopt one compact lineage envelope and propagate it through derived snapshots/APIs.  
**Scope:** Medium · **Priority:** Next

### [OUTCOME-01] Performance summaries need statistical guardrails
**Severity:** MEDIUM  
**Area:** Decision Analytics  
**Evidence:** `decision_outcomes.py:performance_summary` provides counts, means, rates, grouping and decay, but not medians, dispersion, intervals, minimum-sample flags or tail summaries. The frontend labels market outcomes carefully, yet small cohorts remain visually comparable.  
**Why it matters:** Rates and decay from a handful of decisions invite false precision; means hide skew.  
**Recommended action:** Add n, missingness, median, quantiles/dispersion and conspicuous low-sample labels; retain BLOCK as avoided/opportunity observation, never P&L.  
**Scope:** Medium · **Priority:** Next

### [COHORT-01] Historical context has no maximum-age validity
**Severity:** MEDIUM  
**Area:** Regime / Cohorts  
**Evidence:** `DecisionOutcomeRepository.load_context_history` includes a pre-window seed and bounded histories; `decision_outcomes.py` selects observations at or before decision time, preventing look-ahead, but an arbitrarily old seed can classify a later decision.  
**Why it matters:** No-look-ahead is correct, but stale context can be falsely precise. Combined signatures also fragment already small samples.  
**Recommended action:** Centralize per-context max age, return `unavailable_stale`, and suppress/rank sparse combined cohorts.  
**Scope:** Small · **Priority:** Next

### [PRICE-01] Canonical selection is priority-first, not consensus-aware
**Severity:** MEDIUM  
**Area:** Pricing  
**Evidence:** `PriceAuthority.get_price` returns the first positive cached value; freshness is assessed elsewhere and malformed timestamps become “now.” `PriceValidator` tests pairs but does not choose a median/quorum price.  
**Why it matters:** Research can use a stale/outlier preferred source even when two lower-priority sources agree. Timestamp parse failure can look fresh.  
**Recommended action:** Preserve execution tiering, but return invalid timestamp as invalid, apply freshness inside authority, and expose median/quorum reference plus disagreement without automatically changing execution behavior.  
**Scope:** Medium · **Priority:** Next

### [MARKET-01] Funding contracts are insufficiently explicit across venues
**Severity:** MEDIUM  
**Area:** Derivatives  
**Evidence:** `drift_ingest.py` stores `funding_rate` and an `annualized` calculation, while repositories/backtester consume a generic rate; Hyperliquid websocket stores midpoint only and is not scheduler-instantiated. Regime/basis modules use generic fields without a shared interval/sign contract.  
**Why it matters:** Provider period, long/short sign and annualization can be compared incorrectly; historical basis cannot reconstruct depth.  
**Recommended action:** Define rate period, sign convention, annualization basis, mark/index/basis and source timestamp in one normalized funding observation.  
**Scope:** Medium · **Priority:** Next

### [API-01] API response and error contracts vary across a very broad surface
**Severity:** MEDIUM  
**Area:** API  
**Evidence:** 47 route modules mix bare lists, dictionaries, response models, `400/422`, empty fallbacks, and locally shaped `data_quality`; calculation POSTs and durable mutations are separated by auth policy but not consistently labeled in schemas.  
**Why it matters:** The frontend must know each shape and cannot uniformly render freshness/degradation/errors.  
**Recommended action:** Add a shared optional metadata/error envelope incrementally to high-value research families; do not mass-rewrite endpoints.  
**Scope:** Medium · **Priority:** Next

### [DB-01] Analytical reads can multiply into bounded but expensive query loops
**Severity:** MEDIUM  
**Area:** PostgreSQL / Performance  
**Evidence:** `/api/decisions/performance` evaluates up to 100 decisions and calls `load_horizon_prices` per decision for four horizons before separately loading context history. Existing timestamp indexes are mostly single-column; market/funding analytics commonly filter venue/market plus time.  
**Why it matters:** The present bound is safe, but latency grows as history grows and blocks request workers.  
**Recommended action:** Batch horizon-price retrieval and add evidence-driven composite indexes after query-plan measurement. Avoid materialized summaries until measurement requires them.  
**Scope:** Medium · **Priority:** Next

### [EXEC-01] Live adapters remain intentionally prototype-grade
**Severity:** MEDIUM  
**Area:** Execution  
**Evidence:** `config.py` says adapters await native signing/integration testing; Hyperliquid can return `execution_state_unknown`; Jupiter has independent operator, direct-swap, mode and live gates; default is paper.  
**Why it matters:** Safety gates are good, but enabling them does not create complete reconciliation, venue conformance or operational readiness.  
**Recommended action:** Keep live disabled. If ever pursued, require official clients/signing, testnet fault campaigns, durable reconciliation and operator runbooks first.  
**Scope:** Large · **Priority:** Later

### [TEST-01] Important guarantees still rely partly on source-text assertions
**Severity:** MEDIUM  
**Area:** Tests  
**Evidence:** 16 test files read implementation source. Examples assert import strings, route strings and migration text in `test_decision_audit.py`, `test_frontend_alignment.py`, `test_redis_reliability.py`, and `test_final_decision_boundary.py`. Strong behavioral tests coexist with these checks.  
**Why it matters:** A string can remain while behavior breaks, and harmless refactors can fail tests.  
**Recommended action:** Replace the highest-value static checks with API/repository/runtime behavior tests, especially isolation, no-look-ahead, linkage and degraded data.  
**Scope:** Medium · **Priority:** Next

### [BACKTEST-01] Historical buy-and-hold can create repeated fills
**Severity:** MEDIUM  
**Area:** Historical Backtesting  
**Evidence:** Executing the full test suite failed `tests/test_historical_backtester.py:test_historical_decision_fills_on_later_tick_not_signal_tick`: the three-tick, zero-latency buy-and-hold case returned two fills rather than the expected single later-tick fill (`backend/compute/backtester.py:run_backtest`).  
**Why it matters:** A repeated entry changes exposure and economics, so even a correctly ordered event stream can produce an incorrect strategy result.  
**Recommended action:** Reproduce the strategy state transition, ensure buy-and-hold emits one opening intent, and retain the later-tick no-look-ahead condition.  
**Scope:** Small · **Priority:** Now

### [REDIS-01] Legacy idempotency claims are not decoded to the canonical state
**Severity:** MEDIUM  
**Area:** Redis / Execution Safety  
**Evidence:** The suite failed `tests/test_redis_reliability.py:test_legacy_idempotency_value_still_counts_as_claimed`: `StateStore.get_idempotency("legacy")` returned a value without canonical `state="claimed"` for stored legacy value `"1"` (`backend/core/state_store.py:get_idempotency`).  
**Why it matters:** During compatibility periods, a prior claim may not be recognized uniformly, weakening duplicate-request interpretation.  
**Recommended action:** Normalize legacy values at the state-store boundary and behaviorally test claim/status/read paths.  
**Scope:** Small · **Priority:** Now

## 7. Low Priority / Cleanup Findings

### [CODE-01] Oversized orchestration modules concentrate change risk
**Severity:** LOW · **Area:** Code Quality  
**Evidence:** `execution_routes.py` is 784 lines, `backtester.py` 699, `yfinance_ingest.py` 693 and `decision_outcomes.py` 651.  
**Why it matters:** Local changes can cross unrelated responsibilities.  
**Recommended action:** Extract only stable internal helpers during related work; no architectural rewrite.  
**Scope:** Medium · **Priority:** Later

### [STATE-01] Compatibility keys lack a retirement signal
**Severity:** LOW · **Area:** Redis  
**Evidence:** `state_keys.py` declares canonical and legacy WITS, stablecoin, prediction and integrity keys; writers often publish both.  
**Why it matters:** Dual contracts increase ambiguity indefinitely.  
**Recommended action:** Instrument legacy reads, document owners, then remove only when unused.  
**Scope:** Small · **Priority:** Later

### [DOC-01] Narrative documentation overstates provider semantics
**Severity:** LOW · **Area:** Documentation  
**Evidence:** `Explanation.md` describes official bilateral rates updating and trade-volume weighting; current WITS parsing drops dimensions/trade value and samples may drive the aggregate. `codebase.md` header stops at an earlier PR state and omits outcomes/sensitivity/cohorts.  
**Why it matters:** Readers infer capabilities the code does not provide.  
**Recommended action:** Correct provider claims and update capability chronology after truthfulness fixes.  
**Scope:** Small · **Priority:** Now

### [FRONT-01] Provenance, freshness and uncertainty are not first-class across tabs
**Severity:** LOW · **Area:** Frontend  
**Evidence:** decision scripts show detailed replay/outcome semantics, but general `app.js/ui.js` views consume many endpoint-specific shapes and do not provide a shared source/as-of/age/quality panel.  
**Why it matters:** Operators cannot quickly distinguish observed, stale, proxy and synthetic values.  
**Recommended action:** Add a reusable evidence badge/inspector and freshness heatmap before more dashboards.  
**Scope:** Medium · **Priority:** Next

### [SEC-01] Mutation protection is an exact-route maintenance list
**Severity:** LOW · **Area:** Security  
**Evidence:** `operator_auth.py` protects explicit method/path pairs and patterns. It correctly covers current durable/execution mutations, but a new mutation is public unless manually added.  
**Why it matters:** Route growth can cause authorization drift.  
**Recommended action:** Add a route-inventory test requiring each mutation to declare public-calculation or operator-protected intent.  
**Scope:** Small · **Priority:** Next

### [QUALITY-01] Broad fail-soft exception handling can hide persistent outages
**Severity:** LOW · **Area:** Reliability  
**Evidence:** application startup treats migration and scheduler failures as nonfatal; provider/repository modules frequently catch `Exception` and return empty/degraded results. Readiness exists, but callers vary in surfacing it.  
**Why it matters:** Research availability is preserved, but long-lived absence can resemble empty data.  
**Recommended action:** Preserve fail-soft research behavior while standardizing reason codes, counters and as-of age.  
**Scope:** Small · **Priority:** Next

### Informational observations

- **[ARCH-01]** The monolith is appropriate; route/compute/repository separation should remain.
- **[RISK-01]** Existing leverage, margin, loss, throttle and notional controls are enough for current paper research; scenario exposure is more valuable than more limits.
- **[ML-01]** ML is governed but secondary: without an active artifact, `inference.py` uses a visible deterministic heuristic fallback.
- **[UI-01]** The vanilla frontend is viable and does not justify a framework migration.

## 8. Data Provider Audit

| Provider | Purpose | Runtime Status / cadence | Persistence | Authority | Fallback | Key Risks | Recommended Improvement |
|---|---|---|---|---|---|---|---|
| WITS SDMX | tariffs | scheduled 6h | per-query Redis success; aggregate Redis; no tariff fact table | declared authoritative | sample rows | invalid dimensions, lost metadata, synthetic aggregate | validate/map dimensions; persist facts/raw hash |
| GDELT DOC 2.0 | macro news | scheduled 5m, 50 newest | one Redis aggregate, 10m TTL | nonauthoritative context | empty | no article history/regions; tone discarded | persist normalized article/event evidence |
| Pyth Hermes | SOL/USD oracle | 30s | market ticks + snapshot | authoritative execution tier | Kraken/CoinGecko | SOL-centric; staleness split from selection | explicit timestamp validity/quorum view |
| Kraken public ticker | SOL/USD spot | 30s | market ticks + snapshot | execution-eligible corroborator | CoinGecko | single symbol | normalize symbol/source timestamps |
| CoinGecko simple price | SOL/USD | 60s | market ticks + snapshot | execution-eligible corroborator | Yahoo research | rate limits, aggregate quote | backoff and quality history |
| Yahoo/yfinance | crypto/equity/news research | crypto 60s; equities on demand | crypto ticks; caches/process data | research only | Stooq/demo in equities | unofficial fragility/demo confusion | cache, label every artifact, never execution eligible |
| Stooq | daily equity history | on demand | response only | research fallback | seeded demo history | demo fallback may look empirical | explicit synthetic flag and no mixing |
| Drift public market | SOL perp mark/funding | 60s | market/funding ticks + snapshots | funding marked authoritative | none | period/sign convention | normalized funding contract |
| Hyperliquid websocket | SOL midpoint | registry says enabled, but not started by `IngestScheduler` | Redis snapshot only | nonauthoritative | none | registry/runtime mismatch; no durable depth | wire lifecycle or mark disabled; persist selected observations |
| Jupiter quote API | route/quote and gated swap | request-time | order lifecycle only when used | execution prototype | none | direct path distinct from router | keep disabled; research quote semantics |

Retries are primarily periodic retry at the next schedule; provider clients have reasonable 10–30 second timeouts, but no consistent exponential backoff/rate-limit metadata. Scheduler leases prevent duplicate polling only when Redis is available; fail-soft local polling can duplicate across workers when it is unavailable. That trade is acceptable for research but should be visible in ingest status.

## 9. WITS / Tariff Intelligence Audit

**A. Correctness fixes.** Resolve DATA-01 first. `index_calc.py` expects rates/trade values and supports rate-of-change/history, but ingestion does not preserve reliable reporter/partner/product/year coordinates from the response. `geopolitical_routes._state` first requests `wits:tariff:USA:ALL:ALL`, a key the configured `fetch_all` does not normally write, then uses a legacy aggregate. Pressure, rate, change, index and shock are different quantities and should carry distinct units. Centralize `normal/elevated/severe` thresholds used by rules and cohort classifiers.

**B. Coverage gaps.** Current configured “product” names are broad labels, not a country/product explorer or HS nomenclature. There is no durable bilateral/product tariff series and no trade-flow denominator. Complement WITS with UN Comtrade trade values and WTO tariff/download data only after normalized WITS coordinates exist.

**C. Research enhancements.** Add an as-of tariff fact query, bilateral/product contribution decomposition, revision-aware history, and a tariff event timeline. Cohort analytics should attach the latest valid observation at or before decision time with maximum age; tariff schedules are naturally low frequency, so six-hour polling is more frequent than underlying releases but useful for recovery, not freshness.

**D. Optional future.** Government customs notices and agriculture-specific data are valuable for targeted event studies. Full customs-line coverage, every HS revision, and commercial real-time customs feeds are not justified now.

Frontend tariff surfaces show index/macro terminal concepts, but should distinguish percentage rate, percentage-point delta, normalized index and model shock with units and source timestamps.

## 10. GDELT / Geopolitical Intelligence Audit

GDELT is used effectively as **media context**, not as a geopolitical fact authority. `GDELTIngestor` queries configured tariff/trade/sanctions phrases and derives a deterministic negative-tone/article-count score. The stored snapshot omits parsed article fields and average tone, so downstream computations often use defaults. Conflict detection is therefore not distinct evidence extraction: `conflict_escalation.py` and shipping/sanctions modules derive region-specific structures from global aggregate values plus static maps.

Sanctions need authoritative change records (OFAC Consolidated/SDN downloads, EU consolidated list, UK Sanctions List). Conflict needs event-level geocoded observations (GDELT Events or ACLED where licensing permits) rather than DOC tone. Shipping needs observed port/chokepoint/freight data; energy needs EIA inventory/price/supply observations; natural disasters can use GDACS/USGS. Each fills a specific evidence gap; none should be blended invisibly into one score.

Expected impact (`geopolitical_market_impact.py`) is cleanly a deterministic mapping. Observed market reaction exists elsewhere through Yahoo cross-asset/equity histories and macro event reaction endpoints, but there is no integrated event-time matrix matching expected direction against energy, gold, defense, semiconductors, China/EM and crypto windows. Build that as a read-only event study; do not feed it back into risk weights without validation.

## 11. Geopolitical API Endpoint Audit

| Endpoint(s) | Purpose / inputs | Source / compute | Output/state | Limitation / enhancement |
|---|---|---|---|---|
| `/api/geopolitical/index` | composite current risk | Redis GDELT/WITS/stable/cross → `compute_geopolitical_index` | score/components | defaults dominate; add lineage/ages |
| `/events` | normalized proxy events | computed component details | generated events, not persisted | label synthetic proxy; persist real source events |
| `/sanctions`, `/impact`, `/entities` | sanctions proxy/entity view | GDELT/WITS + static programs/demo entities | current computed payload | add authoritative lists/change history |
| `/conflicts`, `/conflict/hotspots`, `/escalation`, `/market-impact` | conflict views | aggregate GDELT + static mappings | duplicated projections | share one computed snapshot; require geocoded evidence |
| `/chokepoints`, `/shipping-risk`, `/supply-chain-impact` | shipping proxy | global shock + static chokepoints | deterministic rows | add observed shipping/freight data |
| `/energy-shock`, `/commodity-impact` | energy/commodity proxy | shock + sanctions | mapped assets | add observed energy/agriculture data and units |
| `/market-impact` | expected cross-asset mapping | composite + generated events | directional expectations | join separate observed-reaction matrix |
| `/scenario-templates`, `/scenario-run` | research scenarios | user shocks/current index | proposal only, not persisted | validate bounded inputs; compare scenarios |
| `/agents/signals` | five proposal agents | current composite | concatenated signals | version thresholds and expose evidence |
| `/reports/daily-brief`, `/reports/protection-brief` | current summaries | recomputed routes/protection | ephemeral report | timestamp constituent data, exports later |

Repeated calls recompute `_state()` and related components; the duplication is modest now, but a single request-scoped computed bundle would keep timestamps consistent. Inputs are mostly query-free; `scenario-run` accepts a generic dictionary and deserves explicit schema/bounds.

## 12. Market Pricing / Price Authority Audit

The intended separation is correctly implemented: Pyth, Kraken and CoinGecko form `_EXECUTION_PRICE_PRIORITY`; Yahoo is appended only after explicit `include_research_fallback=True`. Yahoo cannot make integrity `OK`, and Yahoo-only data cannot satisfy live readiness. Tests in `test_yfinance_research_fallback.py` behaviorally verify default exclusion and Pyth preference.

Research requirements are met by minute polling and on-demand histories. Execution-grade requirements are not met merely by polling: freshness must be validated at the final boundary, malformed/missing timestamps must fail closed, and two independent sources are required. WebSockets would improve execution research/microstructure, but are not necessary for the dashboard; Hyperliquid's current websocket should first be consistently lifecycle-managed.

BTC/ETH/SOL Yahoo aliases are centralized, but execution providers/snapshots are largely SOL-specific while configured execution markets are broader. Unsupported symbols truthfully return not found in `PriceAuthority`; the UI should expose that coverage. Confidence values are provider-assigned rather than calibrated historical reliability. Add provider disagreement/uptime history before treating confidence quantitatively.

## 13. Market Data / Funding / Derivatives Audit

`market_ticks` and `funding_ticks` provide durable bases; Drift persists mark/funding, Hyperliquid provides a runtime midpoint, and compute modules cover basis, carry, funding arbitrage, microstructure, liquidation and slippage. Annualization/sign/unit contracts need consolidation (MARKET-01). Depth and order-book imbalance are mostly current/derived, so historical reconstruction cannot reproduce a full microstructure state. Persisting every book update would be excessive; periodic top-of-book/depth snapshots with source timestamps is sufficient.

Contango/backwardation classifiers should consume a common normalized rate/basis observation and record threshold version. Carry/basis logic exists, but cross-venue mark/index/funding alignment and venue fee schedules are incomplete. Avoid a new market database; extend existing tick schemas only after a concrete research query is defined.

## 14. Stablecoin Intelligence Audit

USDC/USDT/DAI monitoring computes depeg bps, warning (>20 bps), alert (>50 bps), simple liquidity stress and a heuristic peg-break probability. The mathematics clearly separates depeg bps from a 0–1 stress/health concept inside compute, but downstream historical cohort semantics accept both normalized health and depeg categories and need explicit source field/unit.

`stablecoin_ticks` exists and cohort history can read it, yet current stablecoin routes do not persist observations through a repository and `history` usually returns empty cached data. Resolve STABLE-01, then add observed source/as-of, durable ticks, and missingness. High-value additions are supply change and exchange liquidity/redemption proxies from issuer/public on-chain sources. Adding more tokens before USDC/USDT/DAI history is truthful would dilute focus.

## 15. Decision Ledger / Final Decision Boundary Audit

The linkage is coherent:

```text
execution_pre_trade_final.id
  input_provenance.admission_decision_id -> execution_admission.id
execution_admission.id -> order_intents.decision_id -> orders.intent_id -> fills.order_id
```

`execution_routes.submit_order` builds admission evidence and the intent; `ExecutionRouter` computes data/risk/agent results, records the final decision and uses the admission reference. `DecisionRepository` is append-only by API shape. Hashing normalizes the record, and component/config snapshots enable exact recomputation. Naming remains a cognitive risk because APIs return `decision_id` for admission while the final ID is separate; return both explicitly wherever lifecycle data is displayed.

Records with partial provenance, missing model artifacts or old replay inputs correctly become unavailable rather than silently using current state. This is a sufficient decision ledger for research reproducibility when records are complete; it is not a guarantee that every historical row is replayable. Add a completeness dashboard by decision version rather than weakening exactness.

## 16. Decision Outcome & Performance Lab Audit

`HORIZONS` covers 1h/4h/24h/7d. `evaluate_decision_outcomes` calculates buy return as future/decision − 1 and reverses sign for sells. It separates decision quality from requested-side favorability, classifies ALLOW/BLOCK positive/negative/flat, and never claims blocked P&L. Lifecycle data is supplemental for allowed decisions.

The lab groups by market, venue, heuristic and model, reports quality/favorable rates, average signed return, BLOCK avoided-adverse/opportunity cost observations and performance decay. These are useful descriptive metrics but not statistically sufficient: add medians, interquartile ranges, downside quantiles, missing-horizon counts, uncertainty intervals where sample size permits and minimum-n warnings. Magnitude and hit rate must remain separate. Flat tolerance should be visible/configurable. The UI must repeat “market move, not realized P&L” beside every BLOCK chart.

## 17. Regime & Cohort Analytics Audit

Volatility, funding, shock, tariff, stablecoin and liquidity cohorts plus combined signatures are reconstructed using historical repositories. Selection is at-or-before decision time and a pre-window seed prevents incorrectly dropping context at the filter boundary. Tests cover pre-window and no-future selection in `test_decision_outcomes.py`; this is correct no-look-ahead behavior.

The remaining issue is age, not direction: an old tariff/index/regime/stable observation can survive indefinitely. Add per-source maximum ages and an `unavailable_stale` category. Centralize definitions and versions. Combined signatures are useful for exploration but rapidly sparse; default sorting/filtering should hide inferential comparisons below a documented n while retaining raw rows for audit.

## 18. Counterfactual Replay Audit

The stack is appropriately read-only. Exact baseline replay is mandatory; scenario values are finite/allowlisted; component identities remain locked; inapplicable fields are reported; records are deep-copied. There is no order submission, runtime-state import, model training or audit write. A fill-price override is explicitly hypothetical, and realized overlays interpret BLOCK as avoidance/opportunity, not P&L. Unavailable baselines fail clearly.

Next research value comes from saved/exportable scenario definitions, comparison of several bounded scenarios, and clearer unit/preset metadata—not more mutation fields.

## 19. Counterfactual Sensitivity / Boundary Map Audit

One- and two-dimensional sweeps cap each axis and total cells, reject duplicate/nonfinite values, use the replay allowlist, detect transitions/monotonicity and overlay the same realized market observation honestly. These are good controls.

Bounds are computational, not semantic: users supply absolute values and may compare bps, dollars, ratios and normalized scores without unit guidance. Add field metadata (unit, valid research range, baseline), automatically include baseline where possible, support explicitly labeled percentage-relative presets, and calculate nearest sampled transition (“distance to ALLOW/BLOCK”) plus a local robustness summary. Do not imply continuous exact boundaries between sampled points, and do not add unbounded optimization.

## 20. Historical Backtesting Audit

Historical mode combines market/funding/index/stable/regime/events/orders/fills in event time. Same-tick fills are prevented; pending orders wait past latency. Recorded fill economics avoid double-counting funding, and simulated paths include maker/taker fees, slippage and funding. Runs, configs, results and manifests are persisted through `BacktestRepository`; synthetic mode is distinctly labeled.

Coverage, not mechanics, is the constraint: WITS/GDELT facts are absent from durable normalized history, Hyperliquid depth is runtime-only, and provider gaps are counts rather than source/revision manifests. Persist source IDs, observation ranges, missing intervals, code/component versions and synthetic flags in manifests. Strategy backtest P&L and decision-outcome evaluation are separate modules and should remain so.

## 21. Heuristic System Audit

Agents cover macro, tariff exposure, geopolitical/conflict/sanctions/energy, liquidity, risk, equities, rotation, hedging, protection and execution. Compute engines cover rule evaluation, consensus, allocation, regime, basis/carry and portfolio protection. The rule registry/versioning and heuristic evaluation repository are strong; decision records can carry heuristic IDs/versions.

Overlap exists: tariff/shock thresholds appear in rules, agents, geopolitical compute and cohort classifiers; multiple agents transform the same aggregate into different scores. Conduct a registry-driven threshold inventory, state output units and trace whether each agent feeds admission, research API, or only reports. Remove nothing until runtime/frontend usage is proven. Do not replace deterministic heuristics with language models.

## 22. ML Reliability / Governance Audit

Feature order/schema are fixed in `feature_store.py`; every feature has observed/derived/default/fallback provenance. Datasets are hashed with label definitions; temporal splits precede validation; artifacts are hashed; candidates require explicit promotion; replay requests the historical model identity. These protections are appropriate.

Meaningful integration is limited by data: without an active valid model, prediction uses a transparent heuristic, and many features can be defaults. That is truthful, not a defect. Before new models, improve durable training datasets, calibration, out-of-sample regime reporting and feature missingness. Avoid deep models, online retraining and ML geopolitical scoring until evidence depth improves.

## 23. Risk Engine Audit

`risk_engine.py`, `risk_policy.py`, `PositionLedger`, execution admission and portfolio-risk routes cover leverage, margin, daily loss, cooldown/throttle, notional, slippage, risk-reducing exceptions, gross/net exposure, realized/unrealized P&L, fees and funding. Limits are captured for replay and shared between route/router layers; tests cover throttle and unification.

Paper/live semantics are explicit and live new exposure fails closed under missing integrity/idempotency. Existing VaR/Monte Carlo/stress surfaces are adequate for present research. The highest-value addition is portfolio exposure under named tariff/geopolitical/commodity scenarios, with transparent assumptions—not another family of scalar limits.

## 24. Execution / Paper Trading Audit

Paper execution is the credible default. Durable intent/order/event/fill tables, idempotency, conditionals/OCO/trailing concepts, smart-order state, unknown-state handling and PositionLedger make it useful for execution research. Hyperliquid/Drift adapters require both live mode and independent enablement; Jupiter additionally requires its direct gate and operator boundary.

Safe: default paper mode, final audit before submission, risk/data guardrails, explicit unknown state and gated mutations. Prototype: venue signing/ack reconciliation, Hyperliquid websocket lifecycle, Drift/Jupiter production conformance. Research pages use read/calculation routes; mutation controls are explicitly operator surfaces. True live readiness would require adapter-specific conformance, reconciliation after timeouts/restarts, testnet/end-to-end fault testing, key custody and operational response. It should not be a near-term feature.

## 25. PostgreSQL / Repository Layer Audit

The schema coherently includes events, index/market/funding/stable/regime histories, positions/paper trades, conditionals, agent history, order lifecycle, backtests, heuristic evaluations, ingest runs/provenance, ML artifacts/predictions and decision audit. JSONB is appropriate for immutable evidence/config/result payloads, but typed columns hold primary filters and links.

Indexes cover timestamps/status/link IDs; composite `(venue, market, ts)` indexes may benefit observed analytical queries, but measure plans first. Retention is undefined for high-frequency ticks and predictions. Add an explicit research retention/archive policy before volume is material. Repository methods use parameters; no substantiated dynamic-SQL injection was found. The decision performance N-query pattern is the clearest scale concern.

## 26. Redis / Runtime State Audit

Redis is used for snapshots, leases, pub/sub, throttles, idempotency and shared risk state. Connection handling is centralized in `redis_runtime.py`; no embedded server is started. Research paths often degrade to process/local behavior, while live-critical idempotency/readiness fails closed. TTLs exist for price, WITS, GDELT and stablecoin snapshots.

Risks are stale semantics (consumer checks differ), duplicated work when leases cannot be acquired because Redis is down, and compatibility aliases. Standardize snapshot metadata and age checking; expose duplicate-risk/degraded coordination; instrument legacy reads. Do not make Redis durable truth.

## 27. Provenance / Data Quality Audit

The source registry records provider, category, cadence, authority, fallback chain and storage target. Ingest runs track received/persisted counts and failure/fallback. Provenance rows connect runs to artifacts. Price and ML paths have notably strong eligibility/feature provenance; decision records hold source/run/provenance IDs and component/config versions.

Answers today:

- **Prices:** usually yes—source, timestamp and execution eligibility are visible, though timestamp validity needs hardening.
- **Funding:** partly—provider tick exists, but rate-period/sign semantics are incomplete.
- **Tariffs:** no at derived-score level—aggregate can lose dimensions and samples.
- **Geopolitical scores:** no—formula is explainable, source event lineage is not.
- **Stablecoin health:** no when fallback 1.0 is used.
- **Regimes:** partly—historical row is available, classifier version/age is inconsistent.
- **Decisions/replay:** strong when provenance is complete; explicitly partial otherwise.
- **Outcomes:** market tick matching is auditable, but expose exact tick/source in UI.

Implement PROV-01 as an additive envelope: `sources[]`, observation/as-of, retrieved-at, age, quality, authority, execution eligibility, synthetic flag, run/artifact IDs and transformation/version.

## 28. API Endpoint Audit

| Family | Status / findings |
|---|---|
| `/api/index`, `/events`, `/macro`, `/reports` | useful reads; tariff semantics/source history incomplete |
| `/api/markets`, `/divergence`, `/basis`, `/funding-arb`, `/microstructure` | broad research surface; normalize metadata/units and bounds |
| `/api/geopolitical` | coherent family but prototype evidence; see GEO-01 and section 11 |
| `/api/stablecoins`, `/stable-flow`, `/yield` | computations exist; absent observations can look healthy |
| `/api/execution` | bounded durable mutations; largest orchestration module; operator protected |
| `/api/decisions` | strong pagination (≤200; performance ≤100) and read-only research calculations |
| `/api/backtest`, `/replay`, `/sandbox`, `/heuristics` | research semantics generally explicit; durable runs are mutations |
| `/api/risk`, `/portfolio-risk`, `/allocation`, `/protection`, `/hedge` | proposal/read calculations; response metadata varies |
| `/api/ml` | governed mutation/read split; generic body validation could be typed |
| `/api/equities`, `/cross-asset`, `/macro-sensitivity` | high research utility; provider/demo labels must remain visible |
| `/api/health`, `/ingestion` | rich operational visibility; unify reason/status vocabulary |

**API Endpoint Findings by severity:** HIGH—GEO-01, STABLE-01; MEDIUM—API-01, DB-01; LOW—SEC-01, QUALITY-01; INFORMATIONAL—route organization is discoverable and calculation/mutation intent is mostly sound. Pagination/limits are good in decisions/backtests but several history/feed endpoints accept loose window strings or return unbounded cached structures. Add typed request models to scenario, ML training and execution subroutes incrementally.

## 29. Frontend Research UX Audit

The desk uses vanilla HTML/CSS/JS and Chart.js with dedicated scripts for operator access, decision replay, outcomes and sensitivity. It has loading/render paths and extensive tabs for macro, market, risk, execution, geopolitical and institutional research. The newest decision tools are among the clearest surfaces.

Highest-value additions: (1) universal source/quality/as-of badges, (2) click-through provenance inspector, (3) provider freshness/disagreement heatmap, (4) low-n/dispersion displays in Performance Lab, (5) tariff country/product timeline after normalized data exists, and (6) event-to-observed-market-reaction timeline/matrix with expected-versus-observed labels. Make paper/research/proposal labels persistent near controls. Prefer shared rendering helpers and additive panels; do not replace the frontend stack.

## 30. Security Audit

Operator bearer comparison is constant-time; secrets are not returned; live-capable configurations force authentication; missing configured token fails closed. Mutating execution, model lifecycle, decisions, heuristics, backtests and watchlists are protected. Jupiter has an independent disabled-by-default gate. SQL examined is parameterized, and no concrete path traversal or secret logging defect was substantiated.

The real improvement is preventing auth drift (SEC-01). Also bound generic request bodies and avoid returning raw exception text where provider/internal details could leak; current errors are generally controlled. CORS is not broadened in `main.py`. Idempotency fails closed for live new exposure. These are proportionate controls for a research desk.

## 31. Test Coverage Audit

Strong behavioral coverage exists for decision audit/replay, counterfactual isolation and sensitivity caps, outcome signs/classification/cohorts, operator auth, final boundary, execution safety, paper trading, durable lifecycle, PositionLedger/risk, runtime/Redis behavior, historical backtesting, ingestion provenance, ML governance, state contracts and Yahoo separation.

Weaknesses: static source assertions remain common; mocks hide real PostgreSQL/Redis/provider integration; no authoritative WITS fixture validates actual SDMX dimensions; geopolitical tests mostly validate deterministic response structure; stablecoin missing-data truthfulness is not protected; provider rate-limit/stale/malformed timestamps need behavior tests. Add behavioral tests for final/admission/order/fill linkage, max-age cohort context, batched outcome matching, no research endpoint mutation, and degradation without data stores.

**Executed result:** `.venv/bin/python -m pytest -q` completed with **356 passed, 4 skipped, 3 failed**. The failures expose BACKTEST-01 and REDIS-01; the third is a brittle source-text expectation in `test_ingestion_provenance.py` for a literal WITS constant even though the registry's canonical key assertion passes. No external PostgreSQL/Redis/provider service was exercised by this command.

## 32. Performance / Scalability Audit

Plausible bottlenecks only:

- performance evaluation: up to 100 × four-horizon database matches;
- context reconstruction and numerous sparse grouping passes;
- GDELT/WITS pandas parsing in request-adjacent ingest;
- sequential WITS country/product calls;
- repeated Yahoo ticker/history/news calls and process caches;
- geopolitical routes recomputing the same bundle per nested call;
- large cached frontend payloads without uniform pagination.

Current bounds make these acceptable for research. First measure query timings/provider latency, batch decision outcome prices, cache request-scoped geopolitical bundles, and cap all history outputs. Do not add distributed compute or precompute every analytical permutation.

## 33. Documentation Accuracy Audit

`README.md` and `Summary.md` accurately emphasize research/paper defaults, deterministic replay, operator controls and proposal-only intelligence. They need additions for sensitivity/boundary maps, outcomes and cohorts if absent from later sections. `codebase.md` declares an older post-PR state and omits the newest files/routes. `changelog.md` ends at counterfactual replay despite subsequent capabilities present in code. `Explanation.md` overstates WITS semantics/trade weighting and describes geopolitical/news interpretations more confidently than current evidence permits.

Refresh exact current endpoint inventory, provider authority/fallback table, decision-ID linkage, and observed-versus-expected market reaction terminology. Documentation should say GDELT DOC tone is context, Yahoo news is secondary context, and demo/synthetic rows are never authoritative.

## 34. Missing / Valuable Data Sources

### HIGH VALUE / SHOULD CONSIDER NEXT

| Source | Gap / complement | Key? | Frequency | Value | Complexity | Recommendation |
|---|---|---|---|---|---|---|
| WTO tariff downloads/API | validate tariff schedules; complements WITS | usually no | annual/revisions | High | Medium | add after common tariff schema |
| UN Comtrade | bilateral/product trade weights; complements WITS | account often needed for higher limits | monthly/annual | High | Medium | ingest bounded countries/HS groups |
| OFAC + EU + UK sanctions lists | authoritative entity/program changes | no | daily | High | Medium | replace demo entity claims |
| GDELT Events (or licensed-appropriate ACLED) | geocoded conflict/event evidence | GDELT no; ACLED account/terms | 15m/daily | High | Medium | persist normalized event facts |
| EIA open data | oil/gas inventories, production and prices | free key | weekly/daily | High | Medium | ground energy-shock/event studies |
| FRED / official central-bank series | rates, FX, inflation, macro regimes | free key for FRED | daily/monthly | High | Low | add a focused macro factor set |

### MEDIUM VALUE

| Source | Gap / complement | Key? | Frequency | Value | Complexity | Recommendation |
|---|---|---|---|---|---|---|
| GDACS/USGS | disaster/event shocks | no | near-real-time | Medium | Low | add only to event library |
| USDA WASDE/PSD | food/agriculture supply shocks | no | monthly | Medium | Medium | targeted tariff/food research |
| IMF/World Bank macro indicators | country macro context | often no | monthly/annual | Medium | Low | slow-moving context only |
| issuer transparency + public chain RPC | stable supply/reserve/redemption proxies | mixed | daily | Medium | Medium | only USDC/USDT/DAI initially |
| public freight indices/port statistics | shipping validation | mixed | weekly/monthly | Medium | Medium | start with one reproducible series |

### OPTIONAL / FUTURE

NOAA weather, FAOSTAT, BIS statistics, CFTC commitments, exchange options surfaces and public prediction markets can support specific event studies. Add only when a named hypothesis and durable schema exist.

### NOT CURRENTLY WORTH ADDING

Commercial tick firehoses, global vessel-level AIS infrastructure, dozens of crypto venues, every sanctions jurisdiction, full customs-line real-time feeds, alternative satellite data, and multiple overlapping news sentiment providers would add cost and operational breadth before current evidence chains are complete.

## 35. Missing Features

| Feature | Why / builds on | Infrastructure | Research-only | Value / deferral |
|---|---|---|---|---|
| Provenance inspector + freshness heatmap | makes lineage envelope usable; ingest/data-quality APIs | none beyond current stores | Yes | High; next |
| Event study/reaction matrix | tests expected vs observed; geo events + Yahoo cross-asset | durable event/price joins | Yes | High after event facts |
| Tariff country/product explorer | exposes contributions/history; WITS/index | normalized tariff facts | Yes | High after DATA-01 |
| Robustness/distance-to-boundary | summarizes sensitivity maps | no new service | Yes | High; bounded |
| Rolling performance with uncertainty | avoids point-estimate misuse | batched outcomes | Yes | High |
| Portfolio scenario exposure | links geo/tariff shocks to holdings | existing positions/scenarios | Yes | High |
| Research CSV/JSON export | reproducible offline analysis | existing endpoints | Yes | Medium |
| Historical provider-quality metrics | calibrates confidence and coverage | ingest/provenance | Yes | Medium |
| Regime transitions | studies before/after decisions | regime history | Yes | Medium; defer until sample depth |
| Scheduled briefs/alerts | operator visibility | existing reports/events | Mostly | Medium; defer until truthfulness fixes |

Causal caution labels belong on event studies: observed co-movement is not causal attribution. A historical shock library should be built from persisted facts, not manually named scenarios alone.

## 36. Enhancements to Existing Features

1. **WITS:** normalize dimensions, remove canonical sample contamination, persist/revision-stamp facts.
2. **GDELT/geopolitics:** retain article/event evidence and distinguish proxy, expected impact and observed reaction.
3. **Stablecoins:** unavailable is unavailable; persist observed ticks with source age.
4. **Performance Lab:** batch queries, add medians/dispersion/low-n warnings and magnitude views.
5. **Cohorts:** max-age contexts, definition versions and sparse-bucket safeguards.
6. **Sensitivity:** units/ranges/baseline presets and sampled boundary distance/local robustness.
7. **Price authority:** reject invalid timestamps and expose quorum/median disagreement for research.
8. **Funding:** explicit period/sign/annualization schema and periodic depth history.
9. **Frontend:** one reusable evidence/uncertainty component.
10. **Tests:** replace high-value string checks with behavioral contract tests.

## 37. What Not to Build Yet

- A new frontend framework: current vanilla modules are serviceable.
- A database/ORM replacement: PostgreSQL plus parameterized repositories fit the workload.
- Microservices, streaming clusters or distributed analytical compute: current bounded monolith does not justify them.
- True live execution, autonomous trading agents or self-changing risk policies: adapters/evidence are not ready and the project is research-first.
- More ML model families, online retraining or language-model decision replacement: deterministic evidence and datasets need improvement first.
- A second geopolitical/tariff score beside existing composites: improve inputs and lineage instead.
- Dozens of providers or duplicate dashboards: deepen a small authoritative set.
- Full order-book archival, vessel tracking or global customs infrastructure without a defined study.
- Unbounded multidimensional counterfactual optimization or causal claims from reaction correlations.

## 38. Recommended Cleanup Before More Features

Resolve synthetic/unavailable semantics, define a shared lineage/quality envelope, centralize cohort/tariff/funding units and thresholds, add legacy-key usage telemetry, document admission vs final IDs, batch outcome lookups, and convert critical static assertions to behavior. Split oversized files only opportunistically along proven boundaries. Do not delete sidecar modules until route/frontend/runtime usage is measured.

## 39. Recommended Next PRs

### PR 1 — Truthful source observations and historical lineage
**Goal:** Fix WITS dimensional/fallback behavior and stablecoin missing-data semantics; add normalized provenance fields.  
**Why now:** Current plausible values can be synthetic/unavailable.  
**Files likely affected:** `backend/ingest/wits_ingest.py`, `source_registry.py`, `stablecoin_routes.py`, tariff/stable repositories and migrations, data-quality routes.  
**New production files:** At most one shared observation-quality helper.  
**Existing files enhanced:** providers, repositories, schemas.  
**Tests required:** real SDMX fixtures, provider-empty/error cases, no fake stable price, historical/source lineage.  
**Out of scope:** new providers, UI redesign, score changes.  
**Risk:** Medium. **Research value:** High.

### PR 2 — Geopolitical evidence boundary
**Goal:** Label proxy outputs and persist normalized GDELT evidence; stop presenting demo entities as observed.  
**Why now:** GEO-01 is the largest research-credibility gap.  
**Files likely affected:** GDELT ingest, geopolitical compute/routes, events repository.  
**New production files:** Minimal normalized event schema/helper.  
**Existing files enhanced:** `gdelt_ingest.py`, geopolitical engines/routes.  
**Tests required:** article normalization, regional evidence gating, degraded proxy labels, no authority from Yahoo news.  
**Out of scope:** dozens of feeds or score reweighting.  
**Risk:** Medium. **Research value:** High.

### PR 3 — Outcome statistics and batched evaluation
**Goal:** Add robust descriptive statistics/low-n cautions and eliminate per-decision horizon queries.  
**Why now:** Existing lab is valuable but easy to overinterpret and is the clearest query bottleneck.  
**Files likely affected:** decision outcome compute/repository/routes/frontend.  
**New production files:** None preferred.  
**Tests required:** median/quantiles/missingness, BLOCK semantics, batch equivalence, limits.  
**Out of scope:** realized P&L for blocked decisions or causal inference.  
**Risk:** Medium. **Research value:** High.

### PR 4 — Cohort freshness and definition governance
**Goal:** Add max-age rules, versioned definitions and sparse-bucket warnings.  
**Why now:** Completes correct no-look-ahead with truthful staleness.  
**Files likely affected:** `decision_outcomes.py`, outcome repository/routes/frontend.  
**New production files:** None.  
**Tests required:** old seed unavailable, exact boundary ages, no future attachment, sparse signatures.  
**Out of scope:** regime model redesign.  
**Risk:** Low. **Research value:** High.

### PR 5 — Provenance inspector and data-quality UX
**Goal:** Display source, as-of, age, authority, synthetic/degraded state and lineage IDs consistently.  
**Why now:** Makes the first four PRs operator-visible.  
**Files likely affected:** health/ingestion APIs and frontend shared helpers/styles/tabs.  
**New production files:** One small frontend inspector module if needed.  
**Tests required:** empty/degraded/stale render states and API envelope compatibility.  
**Out of scope:** frontend framework migration.  
**Risk:** Low. **Research value:** High.

### PR 6 — Counterfactual robustness metrics
**Goal:** Add units, safe presets, baseline insertion, sampled boundary distance and local robustness.  
**Why now:** High value on a strong existing foundation after truthfulness work.  
**Files likely affected:** counterfactual sensitivity compute/routes/frontend.  
**New production files:** None.  
**Tests required:** unit metadata, bounded presets, no-transition distance, baseline inclusion, read-only guarantees.  
**Out of scope:** optimization or order simulation.  
**Risk:** Low. **Research value:** High.

### PR 7 — Authoritative geopolitical/trade complements
**Goal:** Add one sanctions feed and one trade-flow/tariff validation source behind common schemas.  
**Why now:** Only after evidence contracts are stable.  
**Files likely affected:** provider ingest, source registry, events/tariff repositories, geopolitical/tariff routes.  
**New production files:** Two provider adapters maximum.  
**Tests required:** fixtures, revisions, rate limits, provenance, source disagreement.  
**Out of scope:** broad provider marketplace.  
**Risk:** Medium. **Research value:** High.

### PR 8 — Geopolitical event-to-market reaction lab
**Goal:** Join persisted events to cross-asset windows and compare expected versus observed direction with causal caution.  
**Why now:** Converts static impact mapping into falsifiable research once evidence exists.  
**Files likely affected:** geopolitical market impact, macro event reaction, market repository, geopolitical frontend.  
**New production files:** One event-study compute module may be justified.  
**Tests required:** event-time windows/no-look-ahead, missing assets, expected/observed separation, Yahoo research labeling.  
**Out of scope:** automatic score feedback or causal claims.  
**Risk:** Medium. **Research value:** High.

## 40. Final Prioritized Roadmap

| Recommendation | Type | Research Value | Correctness Value | Security Value | Complexity | Priority |
|---|---|---:|---:|---:|---:|---|
| Truthful WITS/stable observations | FIX | High | High | Low | Medium | Now |
| Historical single-entry backtest correction | FIX | High | High | Low | Low | Now |
| Legacy idempotency normalization | FIX | Medium | High | Medium | Low | Now |
| Geopolitical evidence boundary | FIX | High | High | Low | Medium | Now |
| Shared lineage/quality envelope | HARDENING | High | High | Low | Medium | Now |
| Outcome uncertainty + batching | RESEARCH FEATURE | High | High | Low | Medium | Next |
| Context max-age/sparse cohorts | HARDENING | High | High | Low | Low | Next |
| Provenance/freshness inspector | UX | High | Medium | Low | Low | Next |
| Funding unit contract | FIX | Medium | High | Low | Medium | Next |
| Price quorum/disagreement view | HARDENING | Medium | Medium | Low | Medium | Next |
| Counterfactual robustness | RESEARCH FEATURE | High | Medium | Low | Low | Next |
| Authoritative sanctions/trade feeds | DATA | High | High | Low | Medium | Later |
| Event reaction lab | RESEARCH FEATURE | High | Medium | Low | Medium | Later |
| Mutation auth-inventory test | SECURITY | Low | Medium | Medium | Low | Next |
| Documentation correction | DOCUMENTATION | Medium | Medium | Low | Low | Now |
| Legacy-key telemetry/cleanup | CLEANUP | Low | Low | Low | Low | Later |

### Explicit final answers

1. **Is the repository architecturally coherent?** Yes. It is a layered research monolith with some route/module sprawl, not a fragmented architecture.
2. **Five biggest weaknesses?** WITS truthfulness/dimensions; geopolitical evidence depth; fake stablecoin pegs; incomplete derived lineage; statistically thin/sometimes expensive performance analytics.
3. **Five strongest areas?** Final decision boundary; exact replay; safe counterfactuals; price-tier separation; durable paper execution/risk accounting.
4. **What needs enhancement before new features?** Provider truthfulness, lineage, outcome uncertainty, cohort age controls, funding units and frontend evidence labels.
5. **Weakest integrations?** WITS parsing/history, GDELT-to-specific-geopolitical claims, stablecoin acquisition/history, Hyperliquid runtime wiring, and demo Stooq fallback.
6. **Are WITS/GDELT used effectively?** Partly. GDELT works as aggregate media context; WITS is scheduled but not yet reliable as dimensional history. Neither supports the specificity currently implied downstream.
7. **Is geopolitics deep enough?** No for the stated macro/geopolitical goal. It is a useful deterministic prototype, not evidence-rich intelligence.
8. **Is pricing separation correct?** Yes in authority/integrity defaults; timestamp validation and consensus selection should improve.
9. **Is Yahoo appropriate?** Yes as explicit research fallback/context. It must stay nonauthoritative and all demo/degraded artifacts must remain unmistakable.
10. **Is Performance Lab sufficient?** Useful but not statistically sufficient; add uncertainty, robust statistics, missingness and low-n safeguards.
11. **Are cohorts correct/useful?** No-look-ahead selection is correct and useful; stale-age and sparse-signature controls are missing.
12. **What is missing in sensitivity research?** Unit/range metadata, baseline-aware presets, nearest sampled boundary distance, local robustness and saved/exportable comparisons.
13. **What provenance improvement is needed?** Carry source/run/artifact/as-of/age/authority/synthetic/transformation version through every derived number.
14. **What should frontend add?** Provenance inspector, freshness heatmap, uncertainty/low-n displays, tariff explorer and expected-versus-observed event reaction matrix.
15. **Highest-value public/free data?** WTO tariffs, UN Comtrade, OFAC/EU/UK sanctions, GDELT Events, EIA and a focused FRED/central-bank set.
16. **What appears overbuilt?** Breadth of sidecar analytical endpoints and overlapping proxy scores relative to evidence depth; not the core ledgers/replay.
17. **What is underbuilt?** Historical source facts, geopolitical authority, stablecoin history, trade dimensions, reaction studies and provider-quality analytics.
18. **What should be cleaned now?** Synthetic semantics, shared quality vocabulary, threshold/unit definitions, legacy-key telemetry, oversized-module hotspots and static tests.
19. **Very next PR?** “Truthful source observations and historical lineage.”
20. **Next sequence?** The eight PRs in section 39, in that order.
21. **What explicitly should not be built?** New UI framework, database replacement, microservices, autonomous/live trading, broad new ML, provider sprawl or unbounded counterfactual optimization.
22. **Is this currently a strong research platform?** Yes for deterministic decision, execution-risk and replay research; only moderate as a macro/tariff/geopolitical evidence platform.
23. **What moves it substantially forward?** Deepen a small set of authoritative historical inputs, propagate lineage end-to-end, quantify uncertainty, and build falsifiable event-to-market studies on top of the existing deterministic/replay foundation.
