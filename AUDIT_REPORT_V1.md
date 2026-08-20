# Unified Macro Markets — Post-PR-39 Repository Audit

**Audit date:** 2026-08-20  
**Baseline:** `AUDIT_REPORT.md` (read in full; left unchanged)  
**Code baseline:** commit `b96a2ba`, merge of PR #39, on the current `work` branch  
**Method:** static inspection of current production code, schemas, routes, frontend wiring, tests, commit history for PRs #31–#39, and an attempted full `pytest -q` run. PR text is treated as intent; only merged code is credited.  
**Status semantics:** 🟢 verified healthy/completed; 🟡 partial/limited; 🔴 unresolved, broken, or a major gap.

## 1. Executive Summary

Unified Macro Markets is now a **coherent deterministic research-first monolith**, not merely a loose collection of dashboards. PRs #31–#39 fixed two of the three original truthfulness defects, materially strengthened the third, and added useful contracts around evidence, outcomes, cohorts, provenance, counterfactual robustness, OFAC/WTO, and event-time reactions. The strongest improvement is conceptual integrity: the code now usually says whether a value is observed, authoritative, proxy, expected, unavailable, synthetic, or research-only.

The project nevertheless remains 🟡 **partially aligned** with its core goal. It can inspect one eligible geopolitical event against strict observed Yahoo history for BTC/ETH/SOL and cross-asset ETF proxies. It cannot yet conduct a defensible longitudinal tariff-event study, reconstruct historical OFAC changes, aggregate many events with statistical safeguards, or analyze funding/basis/liquidity reactions across the same horizons. Historical source depth—not another wide layer of endpoints—is the binding constraint.

**Tracked audit determinations (original findings plus new material findings):** **9 🟢, 13 🟡, 5 🔴.** DATA-01 and STABLE-01 are substantially fixed. GEO-01 is 🟡: sanctions truthfulness is substantially fixed, but conflict, shipping, chokepoint, energy, and commodity specificity remains proxy-driven.

**Overall product-goal alignment: 67/100.** Architecture aligns; durable evidence and crypto-market history do not yet support the breadth of claims and questions the product wants to study.

## 2. Audit Scope & Method
 
The current inventory contains **189 backend Python files, 46 route modules, 41 test files, and 10 frontend JavaScript files**. The browser is still vanilla HTML/JS; `frontend/assets/ui.js` is 1,791 lines, `frontend/assets/app.js` 769 lines, and `backend/api/execution_routes.py` 784 lines. The monolith remains understandable because providers, repositories, pure compute, execution, and routes are visibly separated, although orchestration concentration is rising.

Validation included source searches, direct reading of the principal changed modules, SQL migrations, source registry, and tests. The full suite stopped during collection with **20 collection errors** because the active Python 3.14 environment lacked installed packages (`httpx`, `fastapi`, `pandas`, `psycopg2`, `pydantic`, and `redis`). Those packages are declared in `pyproject.toml`, so this is primarily an unprovisioned environment, while the absence of a lockfile/explicit dev workflow remains a reproducibility limitation. No test pass is claimed.

## 3. What Changed Since `AUDIT_REPORT.md`

| PR | Verified current implementation | Audit conclusion |
|---|---|---|
| #31 | Buy-and-hold opening is state-limited; Redis legacy claims are decoded to canonical state. | 🟢 Correctness regressions addressed in code/tests. |
| #32 | WITS no longer injects samples into canonical aggregate, parses SDMX dimensions, retains provider query/observation lineage, preserves last observed aggregate; stablecoin unavailable values are explicit. | 🟢 Material truthfulness fix. |
| #33 | `geopolitical_evidence.py` and downstream envelopes distinguish observed evidence, evidence-supported proxy, static mapping, scenario, and expected impact; GDELT retains bounded article evidence. | 🟢 Boundary exists; 🟡 underlying evidence depth remains limited. |
| #34 | Decision summaries add distributions, coverage, missingness and low-sample warnings; repository batches horizon retrieval. | 🟢 Original outcome/query issues substantially fixed. |
| #35 | Versioned cohort definitions, immutable recorded-context precedence, max-age/no-look-ahead, and `unavailable_stale` are implemented. | 🟢 Governance substantially complete. |
| #36 | Shared quality badges, provenance inspector, source registry/status, tariff lineage and unavailable stablecoin UX are wired. | 🟢 High-value UX improvement; not universal across all 46 routes. |
| #37 | Sensitivity exposes units, baseline-aware presets, sampled-boundary distance, local robustness and non-monotonic warnings. | 🟢 Mature deterministic research surface. |
| #38 | Contract-v2 envelopes, official OFAC SDN records/deltas, and optional-key WTO observations exist and are execution-ineligible. | 🟡 Correct current ingestion, but OFAC baseline is process memory and history is not reconstructed/durable. |
| #39 | A read-only event study uses strict non-synthetic Yahoo history, explicit time basis, 1h/4h/24h/7d maturity, expected/observed separation, and frontend classifications. | 🟡 Valuable single-event lab; no persistent or multi-event research dataset. |

## 4. Original Audit Findings — Current Status

| Original finding | Original severity | Current status | Verified evidence / why status changed | Remaining gap |
|---|---:|---|---|---|
| DATA-01 — WITS fallback/dimensions | HIGH | 🟢 | `wits_ingest.py:_parse_response` walks provider dimension specifications; empty/error batches carry `observed=False`; `_store_aggregate_freshness` includes only `attrs.observed is True`, reports partial batches, persists provenance, and preserves last observed aggregate. PR #32 tests cover truthfulness. | Durable normalized observations are provenance artifacts rather than a purpose-built tariff history/event model; configured identifiers still depend on provider validity. |
| GEO-01 — unsupported geopolitical specificity | HIGH | 🟡 | PRs #33/#36 add evidence semantics and visible warnings; PR #38 adds authoritative OFAC; PR #39 keeps expected mappings separate from observed prices. | OFAC fixes sanctions, not conflict/shipping/chokepoint/energy claims. Those remain static or global-GDELT-derived proxies and lack authoritative event histories. |
| STABLE-01 — missing becomes perfect peg | HIGH | 🟢 | Stablecoin routes now return `available:false`/null fields; frontend renders `--` and UNAVAILABLE; unavailable observations are excluded; predictor default is neutral 0.5 rather than perfect health. Tests explicitly cover missing data. | Some legacy consumers use permissive `depeg_bps` defaults when handed old-shaped state; contract adoption should remain monitored. |
| PROV-01 — derived lineage stops early | MEDIUM | 🟡 | Ingest provenance, observation-quality envelopes, contract v2, WITS lineage and inspector now exist. | Not every derived index/regime/reaction has durable artifact IDs and transformation lineage; event-study output itself is `persisted:false`. |
| OUTCOME-01 — statistical guardrails | MEDIUM | 🟢 | `decision_statistics.py` provides sample counts, missingness, coverage, median/quantiles/dispersion and low-sample warnings; frontend exposes them. | No inferential claims are appropriate at current sample depth; that is a data issue rather than a missing guardrail. |
| COHORT-01 — stale historical context | MEDIUM | 🟢 | `context_governance.py` centralizes versioned definitions, maximum ages, recorded precedence, no-look-ahead and unavailable-stale semantics. | Sparse cohort interpretation remains inherently limited. |
| PRICE-01 — priority-first canonical price | MEDIUM | 🔴 | `PriceAuthority` still returns the first positive cached Pyth/Kraken/CoinGecko candidate; it does not select a consensus/quorum price. Yahoo exclusion is correct. | Freshness/timestamp validity and disagreement-aware canonical research reference remain needed. |
| MARKET-01 — unclear funding contracts | MEDIUM | 🔴 | Drift funding persists, but generic `funding_rate` is consumed with assumed 8-hour/3-per-day annualization; Hyperliquid websocket supplies midpoint rather than a normalized durable funding series. | Define source interval, sign, quote/base, mark/index, annualization, and venue timestamp in one contract before cross-venue studies. |
| API-01 — inconsistent contracts | MEDIUM | 🟡 | High-value provenance/geopolitical/outcome endpoints have stronger metadata. | Forty-six route modules still mix shapes, error styles, `data_quality`, and bare responses; normalize incrementally, not with a rewrite. |
| DB-01 — analytical query loops | MEDIUM | 🟢 | PR #34 adds bounded batched historical price retrieval in `decision_outcome_repo.py`. | Composite indexes should follow measured query plans as history grows. |
| EXEC-01 — prototype live adapters | MEDIUM | 🟡 | Safety gates, immutable final boundary, paper default, durable lifecycle and unknown-state handling are strong. | Signing/conformance, reconciliation, fault recovery, monitoring and runbooks are not production-ready. Intentional limitation, not a regression. |
| TEST-01 — source-text assertions | MEDIUM | 🟡 | New PR tests include meaningful pure/route behavior and mocked providers. | Numerous frontend/alignment/governance tests still search source text; full suite could not collect in this environment. |
| BACKTEST-01 — repeated buy-and-hold fills | MEDIUM | 🟢 | PR #31 state transition prevents repeated opening fills while retaining later-tick execution. | Full runtime test verification was blocked by environment provisioning. |
| REDIS-01 — legacy idempotency decode | MEDIUM | 🟢 | PR #31 decodes legacy byte/string claims to canonical states and tests the behavior. | Compatibility-key retirement telemetry remains separate STATE-01 work. |
| CODE-01 — oversized orchestration | LOW | 🟡 | Core compute additions are sensibly isolated. | `execution_routes.py`, `ui.js`, `app.js`, backtester and Yahoo ingest remain change-risk centers. Split by responsibility only when touched. |
| STATE-01 — compatibility key retirement | LOW | 🟡 | Canonical state keys remain centralized. | No usage telemetry or dated retirement plan is visible. |
| DOC-01 — provider semantics overstated | LOW | 🟡 | Source registry now clearly labels Yahoo research-only and OFAC/WTO authoritative but execution-ineligible. | README/product narrative and some “LIVE” UI badges still summarize heterogeneous quality too coarsely. |
| FRONT-01 — weak data-quality UX | LOW | 🟢 | PR #36 adds badges, source status, provenance inspection, WITS lineage, missing data, and geo warnings; PR #39 adds event metadata/non-causality. | Extend opportunistically to hidden/older analytics, not a wholesale redesign. |
| SEC-01 — exact-route mutation list | LOW | 🔴 | Operator protection remains route-maintenance-sensitive rather than default-deny by HTTP method/router policy. | A newly added mutation can be omitted. Add behavioral coverage and centralized default-deny mutation policy. |
| QUALITY-01 — broad fail-soft handling | LOW | 🟡 | Quality envelopes increasingly expose degradation. | Broad exception paths still suppress persistent provider/DB failures without a unified observability/alerting layer. |

**Informational observations retained:** 🟢 the repository is a monolith worth preserving; 🟢 ML remains governed and secondary; 🟡 compatibility aliases remain deliberate debt; 🟡 demo/scenario modules remain useful only while visibly isolated from observed history.

### Explicit review of original HIGH findings

- **DATA-01 — 🟢 substantially fixed.** Sample contamination is removed; dimensions/provider IDs, observed-only aggregation, last-good preservation and provenance are present.
- **GEO-01 — 🟡 partly fixed.** Sanctions are now backed by official OFAC records. Conflict, shipping, chokepoints, energy, commodities and trade-policy event claims remain proxy/static unless a specific evidence envelope says otherwise. Market reactions are observed but non-causal; expected directions are simplistic versioned hypotheses.
- **STABLE-01 — 🟢 substantially fixed.** Missing no longer becomes price 1.0, 0 bps, or green STABLE in the API/frontend; the predictor treats missing as neutral.

| Geopolitical subdomain | Status | Current boundary |
|---|---|---|
| Sanctions | 🟢 | Official OFAC observations and deterministic deltas, research-only. |
| Conflict | 🟡 | GDELT-supported/global proxy plus static regions; not authoritative incident evidence. |
| Shipping/chokepoints | 🟡 | Explicit proxy/static mapping; no observed disruption feed. |
| Energy/commodities | 🟡 | Expected/proxy impacts; Yahoo can observe asset returns, not the shock itself. |
| Trade policy | 🟡 | WITS/WTO observations exist, but discrete policy-event timestamps/history do not. |
| Market reaction | 🟡 | Strict observed prices and honest semantics; single-event/on-demand only. |

## 5. Current Architecture

```text
WITS ── WTO ── OFAC ── GDELT ── Pyth ── Kraken ── CoinGecko
                 Yahoo/finance research ── Drift ── Hyperliquid ── Stooq
                                      │
                         ingestion / normalization
                                      │
               observation quality + evidence contracts v1/v2
                                      │
                                 provenance
                              ┌───────┴───────┐
                              ▼               ▼
                   Redis runtime state   PostgreSQL durable state
                              └───────┬───────┘
                                      ▼
                deterministic tariff / macro / geo / market compute
                                      ▼
                    crypto + cross-asset event-time research
                                      ▼
                 decision boundary / risk / paper-first execution
                                      ▼
             outcomes / cohorts / backtest / exact + counterfactual replay
                                      ▼
                         FastAPI → browser research desk
```

### Architectural assessment

- **Understandability — 🟢.** Provider → state/repository → pure compute → API is still the dominant pattern. OFAC/WTO/event study additions respect it.
- **Sidecar compute — 🟡.** Separation is useful for pure, independently testable research functions, but mappings overlap across `macro_events.py`, `geopolitical_market_impact.py`, `shipping_energy_risk.py`, and `geopolitical_event_study.py`. Consolidate vocabulary/version registries, not all computations.
- **Routes — 🟡.** Forty-six routers are broad in aggregate; execution orchestration is especially large. Do not introduce microservices. Extract internal application services from large routes when behavior next changes.
- **Frontend — 🟡.** It remains deployably simple, but `ui.js` is too dense. Split renderers by existing tab, retain vanilla JS and the shared quality-badge helper.
- **Contracts — 🟡.** Evidence contracts v1/v2, source registry metadata, price trust tiers, and ad-hoc `data_quality` coexist. Converge shared vocabulary/envelopes incrementally while preserving distinct authority versus execution eligibility.
- **Do not consolidate:** exact replay versus counterfactual replay, execution-grade versus research prices, expected-impact compute versus observed event study, and Redis runtime versus PostgreSQL durable state. These separations enforce safety and truthfulness.

## Updated Capability Inventory

| Capability | Status | Implementation / key files | Sources | Historical depth | Research value | Execution relevance | Main gap |
|---|---|---|---|---|---|---|---|
| Tariff ingestion | 🟢 | `wits_ingest.py` | WITS | Bounded observations/provenance | High | Context only | No discrete policy-event history |
| WTO trade | 🟡 | `wto_ingest.py` | WTO Timeseries | Current bounded pull | High complement | Ineligible | Optional credential; weak durable history |
| OFAC sanctions | 🟡 | `ofac_ingest.py` | OFAC SDN XML | Current snapshot; in-process deltas | Very high | Ineligible | Restart loses baseline; no reconstructed changes |
| GDELT evidence | 🟡 | `gdelt_ingest.py` | GDELT DOC | Bounded article evidence | Medium | Ineligible | No durable normalized event corpus |
| Geopolitical intelligence | 🟡 | geo compute/routes | OFAC/GDELT/WITS/static | Shallow | High potential | Context only | Non-sanctions specificity is proxy |
| Event Reaction Lab | 🟡 | `geopolitical_event_study.py`, geo routes/UI | OFAC/proxies + Yahoo | 1-month on-demand | High | None | No persistence/aggregation |
| Crypto prices | 🟡 | Pyth/Kraken/CoinGecko/Yahoo ingest, authority | Real providers | SOL durable realtime; Yahoo BTC/ETH/SOL research fallback | Very high | Primarily SOL | Uneven breadth/consensus/history |
| Cross-asset prices | 🟡 | Yahoo/Stooq modules | Yahoo, Stooq | On-demand/demo-dependent by route | High | None | Fragile research source, no unified durable history |
| Funding/perps | 🔴 | Drift ingest, HL websocket, basis/funding compute | Drift, Hyperliquid | Drift limited; HL runtime | Very high | Prototype | Units and multi-asset/venue history |
| Stablecoins | 🟢 | stablecoin routes/monitor/UI | cached market sources | `stablecoin_ticks` possible | High | Risk input | Provider coverage/history still thin |
| Tariff Index | 🟡 | index calc/routes | WITS context | `index_history` | High | Decision context | Event linkage/history |
| Macro predictor | 🟡 | `macro_predictor.py` | derived state | Snapshot/decision records | Medium | Research signal | Heuristic validation depth |
| Decision audit | 🟢 | decision repo/evaluator | immutable inputs | Durable | Very high | Admission evidence | Some records partial provenance |
| Decision outcomes/statistics | 🟢 | outcome/statistics modules | market ticks | As deep as ticks | Very high | Evaluation | Sparse history |
| Cohort analytics | 🟢 | context governance/outcomes | durable contexts | As deep as contexts | High | Evaluation | Low n |
| Historical backtester | 🟢 | `backtester.py` | seven durable streams | DB-dependent | High | Paper research | Source depth |
| Exact replay | 🟢 | decision replay | immutable audit/artifacts | Durable decisions | Very high | Safety | Old partial records unavailable |
| Counterfactual replay/sensitivity/robustness | 🟢 | counterfactual modules | recorded decision | Per decision | Very high | None | Sampling, not global proof |
| Heuristic performance | 🟡 | heuristic performance/repo | decisions/history | DB-dependent | High | Governance | Sparse regimes |
| ML governance | 🟢 | `backend/ml/` | supplied datasets | Versioned artifacts | Medium | Fallback only | Do not expand before data |
| Risk | 🟢 | risk engine/final decision | portfolio/runtime | Durable decision evidence | High | Strong paper gate | Operational calibration |
| Execution | 🟡 | router/adapters/ledger | Jupiter/HL/Drift/paper | Durable lifecycle | Medium for goal | Paper strong/live weak | Reconciliation/native conformance |
| Provenance | 🟡 | ingest repo/quality/inspector | all registered ingest | Run/artifact dependent | Very high | Guardrail | Derived/event lineage incomplete |
| Frontend desk | 🟡 | index/app/ui + labs | APIs | Read-only presentation | High | Operator preview | Density/hidden analytics |

## 7. Major Strengths

1. 🟢 Deterministic final pre-trade recomputation, immutable admission evidence, idempotency, and paper-default execution remain unusually strong.
2. 🟢 Exact replay and isolated counterfactual replay do not submit orders; sensitivity now communicates units and sampled-local limitations.
3. 🟢 Missing-data truthfulness improved materially for WITS, stablecoins, cohorts, and reaction history.
4. 🟢 Expected-versus-observed and authoritative-versus-proxy semantics are explicit in backend and frontend.
5. 🟢 Outcome statistics are batched and guarded against small samples/missingness.
6. 🟢 The monolith’s pure compute/repository/provider separation remains appropriate.
7. 🟢 Yahoo research fallback is deliberately excluded from execution authority and synthetic prices are excluded from event studies.

## 8. Critical / High Findings

No new critical security/correctness defect was substantiated. The two most important product-level high gaps are:

### [HIST-01] No durable normalized shock-event research corpus

**Severity:** HIGH · **Status:** 🔴 · **Area:** Historical evidence  
**Evidence:** OFAC baseline lives in `OFACIngestor._baseline`; the Reaction Lab declares `persisted:false`; WITS/WTO are snapshots/observations rather than a discrete tariff-policy event table; GDELT evidence is bounded.  
**Why it matters:** Multi-event analysis, restart-safe OFAC changes, reproducibility and tariff→crypto research cannot be defensible without immutable event time/evidence/version records.  
**Recommended action:** Add one normalized durable research-event contract/table and persist forward OFAC deltas plus qualified tariff/geo events. Do not add statistics until coverage is sufficient.  
**Scope:** Medium · **Priority:** P0.

### [CRYPTO-01] Historical crypto and derivatives depth is below the product’s questions

**Severity:** HIGH · **Status:** 🔴 · **Area:** Crypto market research  
**Evidence:** Execution-grade ingest/source registry is SOL-centric; Yahoo supplies strict BTC/ETH/SOL research history on demand; funding is chiefly Drift SOL and Hyperliquid midpoint runtime state.  
**Why it matters:** Price-only event reactions cannot answer volatility, funding, basis, liquidity, or cross-venue questions, and Yahoo availability controls reproducibility.  
**Recommended action:** Persist normalized BTC/ETH/SOL spot candles and funding/basis observations with source interval/sign/time contracts, then use them in event studies.  
**Scope:** Medium/large · **Priority:** P1.

## 9. Medium Findings

- **[GEO-DEPTH-01] 🟡 Proxy geography remains broad.** Static chokepoint/conflict/energy mappings are honestly labeled but cannot establish that a location experienced a disruption.
- **[EVENT-STAT-01] 🟡 No multi-event aggregation.** PR #39 is appropriate for one-event inspection only; summary counts are buckets/horizons within one event, not evidence across events.
- **[OFAC-01] 🟡 Restart/baseline semantics.** First run correctly reports no changes, but the in-memory baseline makes deltas unavailable after every restart and prevents historical reconstruction.
- **[FRONT-DENSITY-01] 🟡 Frontend concentration.** The research desk exposes many capabilities, but large renderer/application files raise regression risk and cognitive load.
- **[OBS-01] 🟡 Operational observability.** Fail-soft logs and several health surfaces exist, but persistent provider failures, stale durable history, and research coverage do not share alert thresholds/SLOs.

## 10. Low / Informational Findings

- 🟡 The project metadata name is `United-Marco-Markets` and description is a placeholder, while the repository/product says Unified Macro Markets.
- 🟡 Composite DB indexes are not yet tailored to every venue+market+timestamp research query; measure plans before adding them.
- 🟢 The simple frontend stack and monolith should be retained.
- 🟢 Deterministic/versioned rules are a product strength; additional ML is not presently justified.

## 11. New Findings Since `AUDIT_REPORT.md`

| ID | Severity | Status | Evidence and impact | Recommended action / scope / priority |
|---|---:|---|---|---|
| HIST-01 | HIGH | 🔴 | No durable normalized event corpus; event study output is non-persistent and OFAC deltas are process-local. Blocks reproducible multi-event research. | Persist evidence-bound events and deltas; medium; P0. |
| CRYPTO-01 | HIGH | 🔴 | BTC/ETH/SOL event prices depend on on-demand Yahoo; execution-grade and derivatives paths remain SOL-heavy. | Durable normalized crypto spot+derivatives history; medium/large; P1. |
| OFAC-01 | MEDIUM | 🟡 | `_baseline` is in-memory; first run emits no false additions but restart resets change detection. | Durable hash/snapshot baseline and idempotent delta records; small/medium; P0 within HIST-01. |
| EVENT-TIME-01 | MEDIUM | 🟡 | OFAC `change_detected_at` is observation time, not necessarily legal/effective publication time; API exposes time basis. | Preserve multiple times and prohibit cross-event aggregation without time-basis strata; small; P1. |
| FUND-01 | HIGH | 🔴 | Generic rates assume three periods/day across compute; venue period/sign metadata is absent. | Versioned normalized funding contract and backfill; medium; P1. |
| YAHOO-01 | MEDIUM | 🟡 | Strict path prevents contamination, but a single best-effort provider drives all Reaction Lab price history and requests up to 12 symbols per study. | Cache/persist candles; bounded batch/rate telemetry; medium; P1. |
| EVENT-STAT-01 | MEDIUM | 🟡 | No many-event estimates, uncertainty, overlap control, or multiple-testing guardrails. | Implement only after HIST-01/CRYPTO-01; medium; P2. |
| FRONT-DENSITY-01 | LOW | 🟡 | `ui.js` 1,791 lines and `app.js` 769 lines; reaction UI is correctly integrated but tab code is concentrated. | Split by existing tabs on touch; no framework migration; small; P2. |

## Evidence Authority Audit

| Provider | Category | Observed? | Authoritative? | Execution eligible? | Research/fallback/synthetic | Historical persistence | Provenance | Main limitation |
|---|---|---:|---:|---:|---|---|---|---|
| WITS | Tariffs | Yes when successful | Yes for its records | No | Research; canonical synthetic fallback prohibited | Observation provenance/current aggregate; no policy-event corpus | Yes | Depth/event timing |
| WTO | Trade | Yes | Yes | No | Research; unavailable without config/key, no synthetic canonical | Bounded observations/provenance | Yes | Credential/config and shallow history |
| OFAC | Sanctions | Yes | Yes | No | Research only; no synthetic | Records/provenance; delta baseline not durable | Yes | Restart/history/effective time |
| GDELT | News evidence | Yes articles/aggregate | No | No | Evidence-supported proxy; no canonical synthetic evidence | Bounded evidence/provenance | Yes | Not authoritative incident evidence |
| Yahoo | Market research | Yes on strict path | No | No | Research fallback; legacy helpers can demo, strict study cannot | Crypto fallback ticks plus on-demand history | Metadata retained | Provider fragility/rate limits |
| Pyth | Oracle price | Yes | Authoritative oracle tier | Yes subject to freshness/validation | Primary SOL; no synthetic | `market_ticks` | Source metadata | SOL-centric; authority is not exchange execution price |
| Kraken | Exchange ticker | Yes | No official-policy authority; real venue | Yes validation source | Fallback | `market_ticks` | Source metadata | SOL-only integration |
| CoinGecko | Aggregated spot | Yes | No | Included in current execution tier, but best treated as validation/fallback rather than executable venue | Fallback/research | `market_ticks` | Source metadata | Not directly executable liquidity |
| Drift | Perpetual | Yes | Venue-native | Prototype only | No synthetic canonical | Price/funding ticks | Partial | SOL, interval/sign contract |
| Hyperliquid | Perpetual/websocket | Yes midpoint | Venue-native | Prototype only | Runtime path | Redis snapshot, not full history | Partial | Not scheduler-normalized funding/history |
| Stooq | Cross-asset | Yes when provider succeeds | No | No | Research/fallback; demo paths elsewhere must stay labeled | Limited/on-demand | Provider status | Coverage and durability |

## Crypto Market & Trading Alignment Audit

| Asset | Current real providers | Trust/use | Persistence and realistic research |
|---|---|---|---|
| BTC | Yahoo strict history/current research quote | Research-only, never execution authority | On-demand Reaction Lab and some Yahoo ticks; no robust multi-venue durable market corpus |
| ETH | Yahoo strict history/current research quote | Research-only | Same limitation as BTC |
| SOL | Pyth, Kraken, CoinGecko, Yahoo, Drift, Hyperliquid; Jupiter execution path | Pyth/Kraken/CoinGecko execution validation tier; Yahoo research-only; Drift/HL/Jupiter prototype/gated | Best supported current/durable asset; still lacks normalized comprehensive perps/depth history |

- 🟡 **Uneven support:** PR #39 treats BTC/ETH/SOL equally as a research bucket, but ingest, authority, risk defaults, hedge ratio, backtest defaults and execution remain SOL-centric.
- 🟢 **Yahoo separation:** strict event history rejects demo/synthetic rows and cannot authorize execution, so it complements rather than contaminates execution pricing.
- 🟡 **Price authority:** tier separation is sound; first-source selection and CoinGecko’s inclusion as “execution-grade” corroboration are weaker than a freshness/quorum contract.
- 🔴 **Funding/basis:** not broad enough across BTC/ETH/SOL and venues; units are not normalized. Hyperliquid is meaningful runtime/prototype plumbing, not a durable research integration. Drift is meaningful for SOL funding/mark ingestion but narrow. Kraken is correctly a real ticker source, again SOL-only.

**Single largest crypto-market gap:** 🔴 **a durable, normalized BTC/ETH/SOL spot-and-derivatives history aligned to immutable shock events.** Without it, all higher-order questions about volatility, funding, basis, liquidity and repeated regimes remain unanswerable.

## Tariff → Crypto Research Path

| Step | Status | Verdict |
|---|---|---|
| WITS/WTO observed records | 🟢 | Truthful current observations and provenance exist. |
| Normalization/authority contract | 🟢 | WITS dimensions and WTO contract-v2 metadata are present. |
| Durable tariff-change event with precise time | 🔴 | Observations/index updates are not a normalized policy-event history. |
| Tariff pressure/index/macro context | 🟢 | Deterministic compute and index history exist. |
| Regime/research signal | 🟡 | Rules exist, but historical linkage and validation are sparse. |
| BTC/ETH/SOL observed history | 🟡 | Strict Yahoo history exists; durable/provider depth is uneven. |
| Event/regime outcome analysis | 🟡 | Decision outcomes and a WITS expected direction type exist; no defensible tariff-event cohort. |
| Decision-performance linkage | 🟡 | Framework exists; source/event/context coverage is limiting. |

**Answer:** A defensible discrete tariff→BTC/ETH/SOL reaction study is **not yet available**. All three assets can be observed on the price side, but tariff changes are mostly index/observation updates without legally meaningful event timestamps or deep history. WITS/WTO history is insufficient for repeatable inference. Additional historical persistence and event normalization has greater marginal value than another API.

## Geopolitical Event → Crypto Research Path

| Step | Status | Verdict |
|---|---|---|
| OFAC/GDELT context | 🟢/🟡 | OFAC authoritative; GDELT proxy. |
| Evidence classification | 🟢 | Authority/proxy/expected/scenario boundaries are explicit. |
| Normalized event and time basis | 🟡 | API catalog normalizes eligible runtime events; no durable corpus, detection time may differ from effective time. |
| Expected direction | 🟡 | Deterministic/versioned and honest, but broad one-size mappings are simplistic. Crypto is deliberately UNKNOWN. |
| Actual BTC/ETH/SOL | 🟢 | Strict observed Yahoo rows only; no demo prices. |
| 1h/4h/24h/7d | 🟢 | Reference must be pre-event, target after horizon, lag bounded, future horizons NOT_MATURED. |
| Classification | 🟢 | MATCH/CONTRADICT/MIXED/UNSCORABLE/NOT_MATURED/UNAVAILABLE are explicit. |
| Aggregate later research | 🔴 | No persistence or multi-event statistics. |

### Event Reaction Lab audit

- 🟢 It uses observed strict Yahoo prices; synthetic/degraded results become unavailable.
- 🟢 No-look-ahead is correctly enforced for the reference and target. Horizon maturity is checked against `now`.
- 🟡 A 24-hour maximum pre-event reference and 2-hour target-lag tolerance work well for 24/7 crypto but make weekend equity/ETF horizons unavailable rather than selecting the next distant session. That is conservative and truthful, though cross-asset coverage differs structurally.
- 🟢 Crypto is treated as 24/7 by available timestamp observations. UUP is explicitly labeled a broad-dollar ETF proxy, not spot FX; XLE/GLD/ITA/SMH/FXI/EEM are tradable ETF proxies, not their underlying sectors/countries.
- 🟢 Proxy geopolitical events remain non-authoritative; eligible synthetic events are rejected. OFAC authority is not inferred with `bool(ofac)`.
- 🟢 Every observed movement is explicitly non-causal.
- 🟡 Expected mapping is useful as a falsifiable deterministic hypothesis, but sanctions of different countries/programs receive the same direction map. Crypto is appropriately UNSCORABLE rather than forced risk-off.
- 🟡 Useful for inspecting one event, not estimating a repeated effect.

A later multi-event PR is valuable **only after durable event and market history exist**. Safeguards must include: immutable evidence/time-basis/version fields; predeclared windows; minimum n and coverage; medians/quantiles and robust dispersion; bootstrap intervals (descriptive, not causal); overlapping-event exclusion/flags; market-session/calendar strata; multiple-comparison disclosure; no survivorship/demo rows; source/timestamp sensitivity; winsorized and raw views; event-family/program/asset stratification; and explicit correlation-not-causation language.

## Expected vs Observed Research Integrity

| Area | Status | Assessment |
|---|---|---|
| Geopolitical expected impacts | 🟢 | `claim_type=expected_market_impact`, `observed_market_reaction=false`, and no-causal-claim metadata reach UI. |
| Event Reaction Lab | 🟢 | Expected direction and observed return occupy separate columns/contracts. |
| OFAC records | 🟢 | Actual records are observed/authoritative; expected asset effects remain separate. |
| GDELT/conflict/shipping/energy | 🟡 | Correctly labeled proxy/static mapping, but specific-looking tables may still invite over-reading despite badges. |
| Tariff macro events | 🟡 | Demo tariff context is labeled degraded/synthetic; true tariff observation versus policy event is not yet a durable distinction. |
| Stablecoins | 🟢 | Missing is unavailable, not observed healthy. |
| Funding/basis | 🟡 | Values may be observed, but unit/period ambiguity undermines interpretation. |
| Scenario/PnL panels | 🟡 | Marked proposal/scenario, but prominent “PnL Impact” is modeled, not realized P&L; wording should remain explicit. |

No reviewed PR #39 path presents an expected direction as an observed return. The remaining integrity risk is visual specificity in older proxy/scenario panels, not direct field substitution.

## 17. Historical Data Depth Audit

🟡 Durable tables cover market/funding/stablecoin ticks, indices, regimes, events, decisions, orders/fills, and backtests. This is a good skeleton. Actual depth depends on the scheduler’s lifetime and is uneven by provider/asset. WITS provenance does not equal a tariff-policy chronology; OFAC current snapshots do not equal historical changes; Yahoo on-demand data does not equal a reproducible local market corpus; GDELT bounded evidence does not equal an event archive. Source-specific durable history and immutable event linkage should precede new analytics.

## 18. Decision / Outcome / Counterfactual Research Audit

- 🟢 Decision audit, final boundary, immutable context and replay remain the repository’s strongest systems.
- 🟢 PR #34 statistics correctly distinguish sample size, coverage and missingness and batch price evaluation.
- 🟢 PR #35 prevents stale/no-look-ahead cohort contamination and prioritizes immutable recorded context.
- 🟢 PR #37 makes counterfactual sensitivity baseline-aware, unit-aware, locally classified and honest about sampled/non-monotonic boundaries.
- 🟡 Historical validation can evaluate decisions only where market/context ticks exist. BLOCK decisions remain avoided/opportunity outcomes, not realized P&L.
- 🟡 Counterfactual robustness validates deterministic decision behavior around one recorded case; it does not establish policy effectiveness across regimes.

## 19. Trading & Execution Alignment

1. **Production live-trading system today? 🔴 No.** Adapters, reconciliation, conformance, operations and incident recovery remain prototype-grade; configuration says so.
2. **Strong paper/research trading system? 🟢 Yes.** Final recomputation, auth, risk, idempotency, shared Redis coordination, immutable decisions, order intent/order/event/fill tables, PositionLedger, paper executor, backtest and replay are coherent.
3. **Before real capital:** official signing/client integrations; testnet and fault-injection evidence; durable venue reconciliation after ambiguous responses/restarts; cancel/replace and partial-fill conformance; balance/position reconciliation; secrets/KMS and least privilege; operator runbooks/alerts; latency/staleness SLOs; venue-specific limits; independent risk review; staged capital controls.
4. **Wording:** 🟡 Most execution language is gated/paper/proposal-aware. Generic “LIVE” badges and venue naming can overstate provider availability, not actual order readiness; keep mode/readiness beside every action.
5. **Priority:** Live execution should **not** be near-term. It contributes less to the stated research goal than event/market persistence and validation.

## 20. Provenance / Data Quality Audit

🟢 Ingest runs, provenance artifacts, source registry, quality envelopes, badges and inspector now form a credible auditability base. WITS and WTO/OFAC preserve provider IDs/query/quality, GDELT retains bounded evidence, and strict Yahoo communicates source and synthetic status. 🟡 The lineage chain breaks at some derived scores and at the non-persisted event study. A compact shared lineage envelope—source observation IDs, as-of, transformation/version, quality, authority, execution eligibility—should be reused, not replaced by another parallel contract.

## 21. Frontend Research Desk Audit

The frontend now exposes the strongest *new* capabilities: provenance/source status, stablecoin unavailable states, Decision Performance Lab, counterfactual sensitivity, and the Geopolitical Event → Market Reaction Lab with event time/basis, evidence authority, non-causality, expected/observed, classifications and unavailable/maturity states.

Important backend value still hidden or incomplete includes: per-symbol Reaction Lab constituent timing/lag details; event catalog coverage diagnostics; durable history coverage by provider/symbol/time; OFAC baseline/restart state; WTO configuration status; normalized funding units/source intervals; source-disagreement/quorum pricing; and decision-to-specific-event linkage.

**Is it too dense? 🟡 Increasingly.** Keep the current framework. Reorganize within existing tabs using progressive disclosure: overview → evidence → observed reactions → methodology; split JS renderers by tab; add one reusable evidence drawer; collapse scenario/proxy panels below observed evidence; preserve keyboard/deep-link state. Do not migrate to React merely due to file size.

## 22. Tests / Dependency / Reliability Audit

| Metric | Result |
|---|---:|
| Total collected | Not available; collection interrupted |
| Passed | Not claimed |
| Failed | 0 test failures reached |
| Skipped | Not available |
| Collection errors | **20** |
| Blocked imports | `httpx`, `fastapi`, `pandas`, `psycopg2`, `pydantic`, `redis` |

- 🟢 All named blocked packages are declared in `pyproject.toml`, including pytest. The immediate failure is environment provisioning, not undeclared dependencies.
- 🟡 There is no committed lockfile or clearly separated/reproducible test extra in the inspected root; Python 3.14 also exceeds the minimum without an asserted supported ceiling. A documented `python -m venv && pip install -e . && pytest`/locked CI path would remove ambiguity.
- 🟡 Strong pure behavioral tests exist for WITS/stablecoin/evidence/outcomes/cohorts/robustness/providers/event study, and external providers are mocked in targeted tests. Many frontend checks remain source-string assertions rather than browser behavior.
- 🟢 OFAC/WTO/Yahoo tests are designed to be deterministic/mocked and not require live credentials; WTO runtime is credential-optional and should report unavailable rather than synthesize.
- 🟡 Runtime dependencies (Redis/PostgreSQL) are abstracted/mocked in many tests, but collection-time top-level imports mean even pure tests require a fully installed environment.

## 23. Security Review

- 🟢 Operator auth, paper default, final boundary, immutable records, and live gates are strong defense in depth.
- 🔴 Exact-path mutation protection remains maintenance-sensitive; prefer default-deny for mutating methods under protected routers, with explicit public exceptions.
- 🟡 Live credentials/signers are not production-hardened; this reinforces leaving live execution disabled.
- 🟢 Research endpoints are read-only and PR #39 submits zero orders.
- 🟡 Provider payload sizes/concurrency are bounded in important paths, but rate/timeout/error metrics should be operationally visible.

## 24. Performance / Database Review

- 🟢 Decision horizon reads are batched after PR #34; provider requests in PR #39 are one per unique symbol and horizons are computed locally.
- 🟡 One Reaction Lab request can still fan out to 12 Yahoo calls; caching/persistence is preferable to increasing concurrency.
- 🟡 Existing timestamp and some entity indexes are a reasonable baseline. Before new composite indexes, capture `EXPLAIN (ANALYZE, BUFFERS)` for market history, event-time joins and outcome cohorts at realistic volume.
- 🔴 A future multi-event implementation must not issue event×symbol×horizon provider calls. It must query locally persisted ranges in batches.
- 🟢 Microservices/materialized aggregates are not justified yet.

## Breadth vs Data Depth — Updated Verdict

🔴 **Breadth still materially exceeds evidence/data depth.** Truthfulness and analytical guardrails improved substantially, but the code added better boundaries around shallow history rather than creating deep histories. The next marginal dollar/PR should go to **B: durable event history, BTC/ETH/SOL spot and derivatives history, and statistical validation**, not more providers/features. A small number of new sources can follow only when each uniquely fills an observed-event gap.

## Product Goal Alignment Scorecard

| Category | Score | Status | What exists | Missing / what raises score |
|---|---:|---|---|---|
| Tariff Data & Trade Policy Intelligence | 72 | 🟡 | Truthful WITS + authoritative WTO + index | Discrete dated policy events, deep durable observations |
| Geopolitical Evidence Quality | 68 | 🟡 | Evidence boundary, GDELT retention, OFAC | Authoritative conflict/shipping/event history |
| Authoritative Sanctions Intelligence | 78 | 🟡 | Official OFAC records/deltas | Durable baseline, effective dates, historical reconstruction |
| Crypto Spot Price Coverage | 65 | 🟡 | BTC/ETH/SOL Yahoo; strong SOL sources | Durable multi-source majors, quorum/freshness |
| Crypto Perpetual / Funding Coverage | 38 | 🔴 | Drift SOL, HL runtime, basis compute | Normalized BTC/ETH/SOL venue history |
| Cross-Asset Market Coverage | 70 | 🟡 | Yahoo ETF baskets/Stooq | Durable/session-aware multi-source history |
| Event → Market Reaction Research | 70 | 🟡 | Strict single-event horizons/classification | Persisted many-event engine and coverage controls |
| Historical Data Depth | 43 | 🔴 | Good schema skeleton and replay streams | Source-specific backfill and immutable event corpus |
| Crypto-Specific Reaction Analysis | 58 | 🟡 | BTC/ETH/SOL bucket returns | Per-asset views, volatility/funding/basis/liquidity |
| Regime Analytics | 70 | 🟡 | Versioned fresh cohorts | More event-linked observations and sample depth |
| Trading Decision Evaluation | 84 | 🟢 | Outcomes, statistics, cohorts, replay | Larger representative samples/event linkage |
| Counterfactual Research | 88 | 🟢 | Exact isolated sensitivity/robustness | Leave stable; only evidence-driven refinements |
| Risk / Execution Research | 76 | 🟡 | Strong paper gates/ledger/risk | Venue reconciliation; not near-term priority |
| Provenance & Auditability | 78 | 🟡 | Runs/artifacts/contracts/inspector | Derived/event artifact lineage |
| Missing-Data Truthfulness | 86 | 🟢 | WITS/stables/cohorts/study fail unavailable | Audit older demo/default endpoints continuously |
| Frontend Research Usability | 76 | 🟡 | Major labs and quality semantics visible | Progressive disclosure, coverage/unit diagnostics |
| Production Reliability | 52 | 🟡 | Redis/DB fail-soft/fail-closed distinctions | Reproducible CI, observability, operational proof |
| **Overall Alignment With Core Goal** | **67** | **🟡** | Architecture and truthful single-event workflow align | Deep event+crypto history and multi-event validation |

**DOES THE PROJECT FULLY ALIGN WITH THE CORE GOAL TODAY?**  
🟡 **PARTIALLY — architecture aligns but important capability/data gaps remain.** It can formulate and inspect honest deterministic hypotheses; it cannot yet estimate repeatable tariff/geopolitical relationships across deep crypto market and decision history.

## Direct Answers to Product Questions

### Question 1 — Full alignment?

**PARTIALLY.** 🟢 Decision/risk architecture and BTC/ETH/SOL single-event price inspection align. 🟡 Tariff/geopolitical evidence and price history are shallow. 🔴 Funding/basis/liquidity reactions and repeated historical event analysis are missing.

### Question 2 — Can it trace observation → evidence → context → reaction → outcome → decision quality?

- 🟢 Current WITS/WTO/OFAC observation → evidence/provenance.
- 🟡 Evidence → normalized durable market event/context (runtime normalization, insufficient durable history).
- 🟢 Eligible single event → observed BTC/ETH/SOL price reaction.
- 🟡 Reaction → historical outcome (framework exists, event result not persisted/aggregated).
- 🟡 Outcome → trading-decision quality (strong generic outcomes, weak specific event linkage).

### Question 3 — Five highest-value missing capabilities

1. Durable normalized shock-event/evidence history with restart-safe OFAC deltas and discrete tariff events.
2. Durable BTC/ETH/SOL spot candle history aligned across sources and event windows.
3. Versioned normalized funding/basis contract and BTC/ETH/SOL derivatives history.
4. Many-event reaction statistics with overlap/session/coverage/uncertainty safeguards.
5. Explicit event→decision/context linkage for regime and heuristic-performance evaluation.

### Question 4 — What NEXT?

**Recommended title:** “Durable Geopolitical & Trade Event History Contract.”  
**Exact scope:** one immutable normalized event schema/table/repository; authority/claim/time-basis/source-record IDs; payload/hash/version; idempotent persistence of forward OFAC ADDED/UPDATED/REMOVED and qualified WITS/WTO/GDELT research events; restart-safe OFAC baseline; coverage API. Enhance `ofac_ingest.py`, `wits_ingest.py`, `wto_ingest.py`, `gdelt_ingest.py`, scheduler, migrations, events repository and geo routes. Add an event repository/migration tests and provider persistence tests. **Do not include** event statistics, new providers, ML, trading signals, or frontend redesign.

### Question 5 — Immediately after

1. Durable BTC/ETH/SOL Research Market History & Coverage.
2. Normalized Funding/Basis Observation Contract for BTC/ETH/SOL.
3. Multi-Event Reaction Statistics with predeclared safeguards.
4. Event-linked Decision/Regime Performance.

### Question 6 — Do not add yet

Microservices; autonomous/agentic model rewriting; more ML models; live-execution hardening; options/DeFi/NFT analytics; many more dashboard tabs; a frontend framework migration; additional sanctions jurisdictions before OFAC history is durable.

### Question 7 — More external APIs now?

**Partially, but not next.** Ranked only after persistence:

1. **GDELT Events** — highest unique value for normalized conflict/policy event time beyond DOC aggregates.
2. **EIA** — observed energy supply/inventory evidence to replace energy-shock proxies.
3. **FRED** — reproducible macro controls/regime context; lower urgency than event history.
4. **UN Comtrade** — deeper trade-flow validation, not precise tariff-event timing.
5. **EU/UK sanctions** — jurisdiction expansion only after the OFAC durable contract proves reusable.
6. **Additional derivatives provider** — only one with normalized historical BTC/ETH/SOL funding/mark/index and stable access; unique value is venue comparison.

### Question 8 — Deeper history more than providers?

**Yes.** Existing providers already exceed the repository’s capacity to persist, align, and validate them historically.

### Question 9 — Is Reaction Lab mature enough?

🟡 **Meaningful for transparent single-event inspection, not for general research conclusions.** Event authority/time basis and horizon math are careful; BTC/ETH/SOL and proxy buckets work; market history is single-provider/on-demand; no multi-event aggregation or statistical guardrails exist.

### Question 10 — Multi-event historical analysis next?

**Yes as a target, no as the immediate PR.** First persist normalized immutable events, restart-safe changes, and aligned local market history. Then implement many-event analysis with the safeguards listed in §15.

### Question 11 — Are deterministic heuristics still appropriate?

🟢 **Yes.** Continue versioned mappings, immutable inputs, historical validation, descriptive outcomes and counterfactuals. The limiting factor is observations, not model capacity. ML would add estimation risk and opacity before enough representative data exists; retain the governed fallback but do not expand it.

### Question 12 — Strong enough to leave alone

Final decision boundary and audit linkage; exact replay isolation; counterfactual mutation safety/robustness semantics; cohort freshness rules; outcome descriptive-statistics contract; paper-default execution gates; research-versus-execution Yahoo separation. Change these only for demonstrated defects.

## Recommended Next PR Sequence

| PR | Title / priority | Why now and exact problem | Likely files / new files | DB / frontend | Tests | Out of scope |
|---|---|---|---|---|---|---|
| #40 | Durable Geopolitical & Trade Event History Contract — **P0** | Establishes reproducible events and restart-safe OFAC delta truth before statistics | Enhance ingest modules, scheduler, migrations, events repo/routes; add `research_event_repo.py` if existing repo cannot cleanly own it | New immutable event/evidence columns/table; small coverage surface | restart/idempotency/time-basis/delta/provider mocks | Stats, providers, ML |
| #41 | BTC/ETH/SOL Research Market History & Coverage — **P1** | Removes Yahoo-on-request reproducibility bottleneck | Enhance Yahoo/market repo/scheduler/reaction routes; add coverage service only if needed | Candle/market indexes or normalized tick reuse; coverage UI | gaps, source tier, no synthetic, batching | Execution authority expansion |
| #42 | Funding & Basis Observation Contract — **P1** | Fixes unit/sign correctness and expands core crypto outcomes | Drift/HL ingests, models, repo, basis/funding compute | Migration metadata/backfill; unit badges | venue fixtures, annualization, sign/time | Arbitrage execution |
| #43 | Multi-Event Reaction Statistics — **P1** | Converts isolated inspection into guarded descriptive research | Event-study/statistics, repositories, geo routes; focused renderer | Read-only queries; aggregate panel | overlap, sessions, missingness, intervals, no causality | Causal inference/ML |
| #44 | Event-Linked Decision & Regime Outcomes — **P2** | Tests deterministic rules during shock windows | Decision outcomes/context/repositories | Event link/index; decision lab filters | no-look-ahead, BLOCK semantics, low n | Rule retuning automation |
| #45 | Price Freshness/Consensus Diagnostics — **P2** | Resolves PRICE-01 without silently changing execution | price authority/validator/status UI | None | stale/outlier/quorum/timestamp | Automated venue routing |
| #46 | Incremental API/Frontend Research IA — **P3** | Reduces density and shared metadata drift | high-value routes, tab JS extraction | None | API envelope/browser behavior | Framework migration |

## Next PR Decision Matrix

Scores express this audit’s evidence-based prioritization, not implementation certainty.

| Candidate | Core-goal impact /10 | Research value /10 | Correctness /10 | Complexity /10 | Overbuild risk /10 | Dependency | Timing |
|---|---:|---:|---:|---:|---:|---|---|
| Geopolitical event historical persistence | 10 | 10 | 10 | 6 | 1 | None | **Next / winner** |
| Crypto historical market-depth expansion | 10 | 10 | 8 | 7 | 2 | Event contract helpful | Immediately after |
| Funding normalization | 9 | 9 | 10 | 6 | 2 | Market contract | P1 |
| Multi-event reaction statistics | 10 | 10 | 7 | 7 | 7 | Events + market history | P1 after prerequisites |
| Historical OFAC change reconstruction | 8 | 9 | 9 | 8 | 3 | Durable event contract | Later/backfill phase |
| Cross-venue crypto expansion | 7 | 8 | 6 | 8 | 6 | Funding/market contracts | Later |
| GDELT Events | 8 | 8 | 7 | 6 | 4 | Durable event contract | Later |
| EIA energy | 6 | 7 | 7 | 5 | 4 | Event contract | Later |
| FRED macro | 5 | 7 | 6 | 4 | 4 | Persistence capacity | Later |
| UN Comtrade | 5 | 6 | 6 | 6 | 5 | Tariff-event design | Later |
| EU/UK sanctions | 5 | 6 | 7 | 7 | 6 | Proven OFAC contract | Later |
| Frontend improvements | 5 | 6 | 5 | 4 | 4 | New datasets | Incremental |
| API contract normalization | 5 | 5 | 7 | 7 | 7 | None | Incremental |
| Live execution hardening | 3 | 2 | 8 | 10 | 10 | Research maturity | Not now |

**Winner:** Durable Geopolitical & Trade Event History Contract. It is the prerequisite that prevents every later statistical feature from becoming analysis of ephemeral or ambiguous events.

## What NOT to Build Yet

- 🔴 Live-capital execution, new live venue adapters, or automatic order routing.
- 🔴 Multi-event statistics before immutable event and local market histories.
- 🔴 Autonomous agents/LLMs/ML that rewrite deterministic direction, model, or risk rules.
- 🟡 Microservices, Kafka/data lake infrastructure, or materialized aggregate farms.
- 🟡 Options, on-chain/NFT/social-sentiment breadth, and dozens of extra crypto assets.
- 🟡 EU/UK sanctions or more trade APIs before the existing OFAC/WITS/WTO histories are durable.
- 🟡 React/Vue migration or a wholesale API version rewrite.
- 🟡 Causal language, causal-effect estimators, or “prediction accuracy” claims without adequate design/data.

# Final Verdict

| Dimension | Score |
|---|---:|
| Overall repository quality | **7.7 / 10** |
| Architecture coherence | **8.2 / 10** |
| Data truthfulness | **8.6 / 10** |
| Tariff intelligence | **7.2 / 10** |
| Geopolitical intelligence | **6.8 / 10** |
| Crypto-market research | **6.3 / 10** |
| Event reaction research | **7.0 / 10** |
| Trading research | **8.1 / 10** |
| Historical/replay research | **7.5 / 10** |
| Frontend usability | **7.6 / 10** |
| Production readiness | **5.2 / 10** |
| Alignment with core product goal | **6.7 / 10** |

### What is now genuinely strong

- Deterministic final decisions, immutable audit, paper safety and replay.
- WITS/stablecoin missing-data truthfulness.
- Evidence authority and expected-versus-observed boundaries.
- Outcome statistics and cohort freshness governance.
- Counterfactual sensitivity/robustness integrity.
- Strict non-synthetic, non-causal single-event reaction inspection.
- Provenance/data-quality presentation in the research desk.

### What remains the biggest weakness

- No durable normalized historical shock-event corpus.
- Shallow/uneven BTC/ETH/SOL and derivatives history.
- Funding period/sign/venue contract ambiguity.
- Proxy-heavy conflict/shipping/energy evidence.
- No statistically guarded many-event analysis or direct event→decision evaluation.

### Best next PR

**Durable Geopolitical & Trade Event History Contract**—including restart-safe OFAC deltas and immutable evidence/time-basis/version fields.

### Do not build yet

Live execution; microservices; more ML/autonomous rules; multi-event statistics before prerequisites; more dashboard breadth; framework migration; large provider expansion; causal claims.

### Bottom-line answer

**Does Unified Macro Markets now function as a coherent platform for researching how tariffs and geopolitical events affect crypto markets/prices and trading decisions?**

🟡 **PARTIALLY.** It is now a coherent and unusually truthful platform architecture with a useful single-event Reaction Lab and strong decision/replay research. It is not yet a production-quality longitudinal research platform because durable event history, BTC/ETH/SOL market depth, normalized derivatives data, and multi-event validation remain missing.
