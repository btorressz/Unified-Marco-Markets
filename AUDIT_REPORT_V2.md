# Unified Macro Markets — Post-PR50 Repository Audit V2

**Audit date:** 2026-08-26
**Audited main commit:** `51d00bded767596f3e398aae85a76816fbed5d7f`
**Audit type:** source, schema, route, repository, UI, and test audit; no production changes
**Prior audit:** `AUDIT_REPORT_V1.md` (67/100)

## 1. Executive Summary

PRs #41–#50 succeeded at their central architectural objective. The repository is no longer merely a truthful, historically shallow, single-event application: it now has normalized durable event, spot-bar, funding, and basis contracts; bounded event-target retrieval; an Event Reaction Lab covering prices, derivatives, regimes, and decisions; and descriptive multi-event statistics with explicit sample, missingness, overlap, time-basis, uncertainty, and non-causality governance.

That conclusion is about **capability**, not populated production depth. A fresh deployment still accumulates much of its corpus forward from first ingestion; bootstrap policies are bounded; basis history begins at materializer deployment; authoritative evidence is asymmetric across event families; and no repository fixture proves a large, representative longitudinal corpus. The system is therefore a **credible longitudinal research platform whose realized statistical power depends on operation/backfill**, not yet a mature empirical dataset.

The strongest subsystem is the truth-preserving research chain from immutable event evidence through bounded observations to governed descriptive output. The weakest research dimension is evidence and historical depth outside sanctions/trade. The most important correctness gap is cross-source price disagreement/freshness diagnostics—not a demonstrated need to replace deterministic execution price priority. The most important security gap remains exact-list, default-allow mutation authorization. The most important delivery gap is the absence of GitHub CI. The most important product gap is that the backend's richest PR #50 strata and integrity output are hidden behind coarse summaries or raw JSON.

**Overall alignment: 79/100 (V1: 67/100).** The 12-point increase credits implemented durable contracts and governed multi-event research, while withholding credit for mere schema capacity, thin live populations, hidden UI detail, incomplete evidence authority, CI absence, and prototype live execution.

**Verdict: READY FOR NEXT FEATURE PR**, provided the feature is the bounded, no-schema Multi-Event Statistical Research UX and it is followed promptly by price diagnostics, default-deny auth, and CI. This is not a finding that real-capital execution is ready.

## 2. Audit Scope & Exact Main SHA

The supplied repository had no configured remote. `git fetch origin main` was attempted after configuring the declared public repository URL, but the environment's HTTPS CONNECT tunnel returned 403. The local branch tip was independently resolved as `51d00bded767596f3e398aae85a76816fbed5d7f`, matching the prompt-writing baseline, and contains merge commits for every PR #41–#50. This report therefore calls that exact locally available main snapshot “current main”; it does **not** claim that an inaccessible GitHub ref was reverified.

Initial `git status --porcelain` was empty. The audit branch was created from that tip. Merge history inspected:

| PR | Merge commit | Implemented state verified in source |
|---|---|---|
| #41 | `cf7401c` | normalized `research_events`, restart-safe OFAC/WITS event persistence |
| #42 | `bf1b0cf` | durable BTC/ETH/SOL `research_market_bars` and backfill/incremental policy |
| #43 | `7830842` | history coverage API/UI diagnostics |
| #44 | `b2a0cb9` | BTC/ETH/SOL canonical aliases and asset-scoped integrity/readiness |
| #45 | `cf7007b` | runtime registry/readiness/integrity corrections |
| #46 | `9ff1f30` | versioned funding and basis observation contracts |
| #47 | `f7eb3da` | derivatives runtime materialization and current-vs-realized separation |
| #48 | `16a9a6f` | Reaction Lab v2 derivatives, regime, and decision outcomes |
| #49 | `055053d` | multi-event descriptive statistical validation |
| #50 | `9d69011` | bounded samples, coverage integrity, strata, and decision-cohort fixes |

Method: read both historical audits and the five requested project documents; inspect production modules, migrations, repositories, scheduler/ingest wiring, all mutation decorators, frontend API/rendering, and focused tests; run the full available suite and syntax/compilation checks. PR titles and prose were treated as intent only.

## 3. What Changed Since `AUDIT_REPORT_V1.md`

1. **Durable research inputs:** immutable normalized event rows and BTC/ETH/SOL bars replace process-local/single-request foundations.
2. **Derivatives semantics:** funding observations now carry contract version, rate kind, interval, timestamps, sign/cashflow semantics, annualization context, provider identity, and durable basis observations.
3. **Research composition:** Event Reaction Lab v2 connects events to price, funding, basis, regime, and decision outcomes without causal language.
4. **Repeated-event validation:** candidate/matured/observed denominators, missingness, horizon-specific overlap, deterministic bootstrap, winsorized sensitivity, and event strata exist.
5. **Sample integrity:** repositories accept event-target windows; global dataset coverage is separate from query coverage; mixed time-basis headline results are suppressed; decision cohorts fail closed when truncated.
6. **Runtime hardening:** current market and price-integrity state is asset-scoped for BTC/ETH/SOL.
7. **What did not change enough:** populated historical depth, broad authoritative geopolitical evidence, canonical-price diagnostics, default-deny auth, CI, frontend statistical detail, and live-execution maturity.

## 4. PR #41–#50 Closure Matrix

“Complete” means the contract and required behavior are present, not that every deployment already has a statistically large corpus.

| # | Area | Status | Verified determination |
|---:|---|---|---|
| 1 | Durable normalized geopolitical/trade event history | 🟢 VERIFIED COMPLETE | `research_events` is normalized, immutable/idempotent, evidence-bound, and queryable. |
| 2 | Restart-safe authoritative event persistence | 🟢 VERIFIED COMPLETE | OFAC/WITS baselines and deltas use durable history; first-run semantics avoid false additions. |
| 3 | BTC/ETH/SOL durable research market history | 🟢 VERIFIED COMPLETE | Separate research bars, canonical assets, bootstrap/incremental persistence, partial-failure truthfulness. |
| 4 | Historical market-data coverage diagnostics | 🟢 VERIFIED COMPLETE | first/latest/count/gaps/source diagnostics are exposed distinctly from availability. |
| 5 | Canonical BTC/ETH/SOL current market-data coverage | 🟢 VERIFIED COMPLETE | canonical aliases and readiness checks cover all three. |
| 6 | Price-integrity isolation by asset | 🟢 VERIFIED COMPLETE | integrity keys/readiness/execution lookup are symbol-scoped; unknown fails closed live. |
| 7 | Versioned normalized funding observations | 🟢 VERIFIED COMPLETE | durable contract fields and uniqueness/provenance are implemented. |
| 8 | Funding interval/sign/provider semantics | 🟡 PARTIAL / LIMITED | Hyperliquid semantics are explicit; Drift/Velocity contract-v0 remains deliberately unverified and must not be compared as normalized. |
| 9 | BTC/ETH/SOL perpetual market context | 🟢 VERIFIED COMPLETE | supported Hyperliquid materialization covers the canonical set. |
| 10 | Durable perpetual basis observations | 🟢 VERIFIED COMPLETE | normalized durable basis rows and materializer exist. |
| 11 | Cross-venue derivatives comparability | 🟡 PARTIAL / LIMITED | comparable only for providers/contracts with verified semantics; unsupported v0 observations are isolated. |
| 12 | Funding current-vs-realized separation | 🟢 VERIFIED COMPLETE | instantaneous/current rates are not silently labeled realized interval cashflows. |
| 13 | Derivatives provenance | 🟢 VERIFIED COMPLETE | provider, provider timestamp, observed/ingested time, contract, raw context and run lineage are retained. |
| 14 | Event Reaction Lab v2 | 🟢 VERIFIED COMPLETE | price, funding, basis, regime, decisions and provenance are wired service→route→UI. |
| 15 | Funding reactions | 🟢 VERIFIED COMPLETE | horizon deltas, directions, sign flips, missingness and provenance exist. |
| 16 | Basis reactions | 🟢 VERIFIED COMPLETE | basis deltas and premium/discount transitions exist. |
| 17 | Event-linked regime outcomes | 🟢 VERIFIED COMPLETE | reference/horizon regimes and governed transition matrices exist. |
| 18 | Event-linked decision outcomes | 🟢 VERIFIED COMPLETE | explicit and temporal link semantics plus classifications are present. |
| 19 | Multi-event statistical validation | 🟢 VERIFIED COMPLETE | descriptive aggregation exists across price, funding, basis, regime and decisions. |
| 20 | Sample-size governance | 🟢 VERIFIED COMPLETE | candidate/included/matured/observed counts, minimum-n warnings and sample hashes exist. |
| 21 | Missingness governance | 🟢 VERIFIED COMPLETE | reason taxonomy and reconciled denominators exist. |
| 22 | Overlap-window governance | 🟢 VERIFIED COMPLETE | chronological, horizon-specific exclusion applies to market and regime results. |
| 23 | Event-time-basis governance | 🟢 VERIFIED COMPLETE | basis counts/strata exist and mixed-basis headline statistics are suppressed. |
| 24 | Bootstrap/descriptive uncertainty | 🟢 VERIFIED COMPLETE | deterministic descriptive bootstrap intervals are available only above governed n. |
| 25 | Winsorized sensitivity | 🟢 VERIFIED COMPLETE | raw results remain primary and versioned winsorized sensitivity is disclosed. |
| 26 | Event-family stratification | 🟢 VERIFIED COMPLETE | populated backend grouping with subgroup warnings. |
| 27 | Event-type stratification | 🟢 VERIFIED COMPLETE | populated backend grouping with subgroup warnings. |
| 28 | Event-time-basis stratification | 🟢 VERIFIED COMPLETE | populated grouping; mixed headline suppression directs consumers to it. |
| 29 | Statistical decision linkage | 🟢 VERIFIED COMPLETE | decision aggregation has cohort bounds, classifications, coverage and strata. |
| 30 | Explicit-recorded vs temporal event-decision links | 🟢 VERIFIED COMPLETE | explicit requires immutable recorded evidence; proximity remains labeled temporal-only. |
| 31 | Decision outcome aggregation | 🟢 VERIFIED COMPLETE | ALLOW realized classifications and BLOCK counterfactual market-move classifications are separated. |
| 32 | Statistical sample integrity | 🟢 VERIFIED COMPLETE | PR #50 fixes row shadowing/counts, coverage bounds, mixed time bases and censoring. |
| 33 | Bounded event-target history queries | 🟢 VERIFIED COMPLETE | event-derived start/end bounds replace arbitrary latest-N research slices. |
| 34 | Protection against truncated history as dataset start | 🟢 VERIFIED COMPLETE | dataset first/latest coverage is queried separately from window coverage. |
| 35 | Research-only/no-causal-claim boundaries | 🟢 VERIFIED COMPLETE | API methodology and UI repeatedly state descriptive, non-causal, research-only semantics. |

**Closure result:** 32 complete, 3 partial, 0 broken, 0 intentionally out of scope. The partial items are semantic/provider breadth, not silent ambiguity in supported contracts.

## 5. Original V1 Findings — Current Status

### 5.1 Original audit IDs

| ID | Original severity | V1 | V2 | Verified evidence / change since V1 | Remaining gap, action, priority |
|---|---|---|---|---|---|
| DATA-01 | HIGH | 🟢 | **CLOSED** | Observed-only WITS aggregation remains intact; PR #41 adds immutable normalized tariff research events. | Monitor provider identifier validity; no dedicated remediation. |
| GEO-01 | HIGH | 🟡 | **PARTIAL** | OFAC is authoritative and WITS/WTO support trade; event persistence improves reproducibility. | Conflict, shipping, energy, commodity, cyber and macro-control evidence remain proxy/scenario-heavy. Add one unique observed event source, P1. |
| STABLE-01 | HIGH | 🟢 | **CLOSED** | Missing remains unavailable/null and excluded rather than a perfect peg. | Monitor legacy-shaped consumers, P2 maintenance. |
| PROV-01 | MEDIUM | 🟡 | **PARTIAL** | Events/bars/funding/basis now retain evidence/provider/contract lineage and query integrity. | Derived multi-event reports are computed responses rather than durable artifacts with transformation IDs; add only if reproducible report retention becomes a requirement, P2. |
| OUTCOME-01 | MEDIUM | 🟢 | **CLOSED** | Existing decision guardrails plus multi-event descriptive n/coverage/dispersion/bootstrap/warnings. | Statistical power remains data-dependent, not a missing contract. |
| COHORT-01 | MEDIUM | 🟢 | **CLOSED** | Immutable recorded context precedence, freshness, and PR #50 complete-cohort fail-closed behavior. | Continue censoring disclosure. |
| PRICE-01 | MEDIUM | 🔴 | **PARTIAL** | Authority remains deterministic Pyth→Kraken→CoinGecko, while per-asset validator/readiness gates stale/UNKNOWN/WARNING live data. | Diagnostics do not expose a rich quorum/dispersion/outlier/age matrix. Add diagnostics first; do not replace authority without evidence, P1. |
| MARKET-01 | MEDIUM | 🔴 | **PARTIAL** | Versioned funding/basis rows define kind, interval, timestamps, signs, cashflows, annualization, provider and provenance; Hyperliquid BTC/ETH/SOL is materialized. | Drift/Velocity contract-v0 semantics deliberately remain unverified; cross-venue claims must exclude them. Verify provider contract before migration/backfill, P1. |
| API-01 | MEDIUM | 🟡 | **PARTIAL** | New research endpoints use strong methodology/quality envelopes. | Older route shapes remain heterogeneous; normalize only when touched, P2. |
| DB-01 | MEDIUM | 🟢 | **CLOSED** | Decision batches remain bounded and event-target market/derivatives queries replace latest-row slicing. | Use query plans/index telemetry as actual volume grows. |
| EXEC-01 | MEDIUM | 🟡 | **PARTIAL** | Paper default, immutable final boundary, readiness, durable lifecycle and reconciliation checks remain. | Signing conformance, partial fill/cancel-replace recovery, venue truth recovery, monitoring/runbooks and fault drills remain inadequate for capital, P1 before live work. |
| TEST-01 | MEDIUM | 🟡 | **PARTIAL** | Focused PR #41–#50 tests exercise repositories, services, routes, contracts and critical sample behavior. | Many UI/governance tests still assert source strings; no automated CI, P1. |
| BACKTEST-01 | MEDIUM | 🟢 | **CLOSED** | State-transition fix and behavioral coverage remain present. | No audit-specific action. |
| REDIS-01 | MEDIUM | 🟢 | **CLOSED** | Legacy claim decoding remains normalized/tested. | Retirement telemetry belongs to STATE-01. |
| CODE-01 | LOW | 🟡 | **PARTIAL** | Repository/compute/service boundaries absorbed complex research work coherently. | `ui.js`, `app.js`, large route/orchestration files remain touch-risk. Extract renderers/services opportunistically; no rewrite, P2. |
| STATE-01 | LOW | 🟡 | **PARTIAL** | Canonical and per-asset keys are centralized. | Legacy compatibility keys lack observed-usage telemetry and dated removal, P2. |
| DOC-01 | LOW | 🟡 | **PARTIAL** | Research-only and provider semantics are prominent in current surfaces. | Long-form docs still contain older broad feed/“real-time” prose; reconcile incrementally, P2. |
| FRONT-01 | LOW | 🟢 | **PARTIAL (regressed by capability growth)** | Existing quality/provenance and Reaction Lab v2 summaries are visible. | PR #50 strata, cohort detail and query integrity are largely hidden/raw. Close through PR #52, P0 product priority. |
| SEC-01 | LOW | 🔴 | **OPEN** | `operator_auth.py` still enumerates exact paths/patterns; unmatched mutation methods are allowed. Research/calculation POST exemptions are intentional, but no complete route-inventory assertion prevents omission. | Introduce route metadata/classification and fail startup/test when an external mutation is unclassified; default deny that class, P1. |
| QUALITY-01 | LOW | 🟡 | **PARTIAL** | Quality envelopes now include history coverage and query integrity. | Persistent-provider/history SLOs and unified alerting remain absent, P2. |

### 5.2 Findings introduced in V1

| ID | Original severity | V1 | V2 | Verified evidence / change | Remaining gap, action, priority |
|---|---|---|---|---|---|
| HIST-01 | HIGH | 🔴 | **CLOSED** | PR #41 supplies durable normalized, idempotent, evidence-bound event history. | Population depth covered by DATADEPTH-01. |
| CRYPTO-01 | HIGH | 🔴 | **PARTIAL** | PRs #42–#47 add durable BTC/ETH/SOL bars plus verified funding/basis materialization. | Actual depth is deployment/backfill dependent; basis is forward-only from materialization. P1 operations/data. |
| OFAC-01 | MEDIUM | 🟡 | **CLOSED** | durable baseline/hash and immutable event delta behavior survives restarts. | None beyond normal ingest monitoring. |
| EVENT-TIME-01 | MEDIUM | 🟡 | **CLOSED** | multiple time semantics are preserved; multi-event aggregation counts/stratifies basis and suppresses mixed headlines. | Provider retrieval time still cannot become legal effective time without source evidence. |
| FUND-01 | HIGH | 🔴 | **PARTIAL** | normalized v1 semantics and annualization isolate verified observations. | Do not normalize Drift/Velocity v0 until verified; P1. |
| YAHOO-01 | MEDIUM | 🟡 | **CLOSED** | BTC/ETH/SOL research bars persist independently with coverage diagnostics and bounded retrieval; Yahoo stays research-only. | Provider concentration may affect long backfills but is disclosed. |
| EVENT-STAT-01 | MEDIUM | 🟡 | **CLOSED** | multi-event estimates, uncertainty, overlap, strata, missingness and warnings are implemented. | Empirical n remains corpus-dependent. |
| FRONT-DENSITY-01 | LOW | 🟡 | **PARTIAL** | Feature integration avoided a framework rewrite. | Statistical renderer is dense and hides backend detail; split within current vanilla architecture when PR #52 touches it, P1. |
| GEO-DEPTH-01 | MEDIUM | 🟡 | **PARTIAL** | durable evidence events improve traceability, not authority breadth. | Add observed conflict/shipping event evidence only after UX/hardening, P1. |
| OBS-01 | MEDIUM | 🟡 | **PARTIAL** | readiness, coverage and ingest ledgers exist. | No shared SLO/alert policy for stale research corpora/providers, P2. |

**Closed since V1:** HIST-01, OFAC-01, EVENT-TIME-01, YAHOO-01, EVENT-STAT-01; MARKET-01/FUND-01 and CRYPTO-01 moved from open to partial. Existing closed findings remain closed except FRONT-01, whose broader V2 capability creates a new UX completion requirement.

## 6. New V2 Findings

| ID | Severity / status | Evidence and impact | Recommended remediation / suggested PR | Blocks future work? |
|---|---|---|---|---|
| FRONT-02 | MEDIUM · OPEN · **P0** | Backend returns time-basis/type/family strata, stratification metadata, funding/basis transition counts, regime coverage, decision classifications/link/regime strata, and `data_query_integrity`; UI shows headline medians, raw regime JSON, coarse cohort counts and missingness/overlap JSON. Users cannot efficiently interrogate the governed result. | PR #52, **Complete Multi-Event Statistical Research UX**: structured drilldowns, denominators/warnings and integrity panels; no schema/backend-statistic expansion. | Blocks claiming a complete research product UX, not backend research correctness. |
| PRICE-02 | MEDIUM · OPEN · **P1** | Per-asset validator has threshold status but lacks a consolidated source-age/quorum/dispersion/outlier diagnostic contract. A priority price may be valid while disagreement context is hard to inspect. | PR #53, add read-only diagnostics, health/UI visibility and behavioral tests; do not change execution selection. | Blocks evidence-based decision on authority redesign and contributes to live-readiness gap. |
| SECURITY-02 | MEDIUM · OPEN · **P1** | SEC-01's exact allowlist model persists. New external mutation routes can default allow; calculation POSTs make a blanket method rule inappropriate. | PR #54, classify routes explicitly and inventory every mutating route; fail closed only for external-state mutations. | Blocks safe expansion of mutation surfaces and live deployment. |
| CI-01 | MEDIUM · OPEN · **P1** | `uv.lock` exists, but version constraints are lower bounds, supported Python is only `>=3.11`, and `.github/workflows` is absent. Tests and Node syntax checks do not run automatically on PRs. | PR #55, locked `uv sync --frozen`, supported-version matrix, pytest, compile and Node checks; reproducible service strategy/markers. | Does not block read-only UX, but blocks reliable team delivery. |
| DATADEPTH-01 | HIGH · OPEN · **P1** | Schemas and bounded bootstrap exist, but no checked corpus/deployment telemetry proves representative multi-year or multi-family n; basis/event collections are mainly forward-accumulating. Low-n strata remain likely. | Operational backfill/depth PR after CI: explicit targets, safe idempotent backfill, coverage reports and alerts; avoid synthetic fill. | Blocks strong empirical generalization and causal work. |
| STAT-01 | MEDIUM · OPEN · **P1** | Core denominators are correct, but source-era changes, event clustering/near-duplicates, unequal sessions, mixed authority classes and provider availability can bias descriptive results. | Add diagnostic flags/deduplication sensitivity after more data; preserve raw samples. Suggested post-#56 validation PR. | Blocks stronger claims, not current descriptive research. |
| GEO-02 | HIGH · OPEN · **P1** | Sanctions/trade authority is much stronger than conflict, shipping/chokepoint, energy, commodity, cyber and macro-control evidence. Durable storage cannot repair weak observation authority. | PR #56, bounded GDELT Events expansion with event identity/deduplication/evidence semantics and backfill limits. | Blocks broad geopolitical generalization. |
| OBS-02 | MEDIUM · OPEN · **P2** | Coverage is visible on request but there is no common operational alert for stopped event/bar/funding/basis accumulation. Silent long-lived staleness erodes samples. | Later research-corpus freshness SLO/alert PR using existing ledgers/coverage; no new observability stack required. | Does not block UX; blocks dependable long-running operation. |

**Priority count for new findings:** P0 **1**, P1 **6**, P2 **1**.

## 7. Current Architecture

The modular monolith remains appropriate. FastAPI routers are numerous, but domain repositories isolate SQL, compute modules remain largely deterministic, provider adapters retain native boundaries, and services compose event research without crossing into execution. This is exactly where an internal service/repository architecture provides useful separation without distributed-system cost.

Concentration remains visible in `frontend/assets/ui.js`, `frontend/assets/app.js`, and some route/orchestration modules. PR #52 should extract small statistical render helpers if useful, preserving vanilla JS and existing tabs. **Do not introduce microservices, Kafka, or a frontend framework migration.** There is no overwhelming scaling/fault-isolation evidence for those changes.

## 8. Durable Event History Audit

`research_events` supports immutable IDs, event type/family, provider/evidence identity, observed/effective/change-detected time fields, event-time basis, payload hashes, provenance and idempotent inserts. Repositories provide bounded list/query behavior. OFAC first observation establishes a durable baseline without inventing additions; later differences produce reproducible immutable events. WITS observations are persisted without presenting continuous tariff snapshots as false discrete legal announcements.

The architecture closes HIST-01 and OFAC-01. It does not create historical events that were never backfilled or give a retrieval timestamp legal-effective authority. Corpus depth and authority-class mixture must remain visible.

## 9. Crypto Spot History Audit

`research_market_bars` is distinct from operational `market_ticks`. It supports BTC/ETH/SOL, normalized intervals, source timestamps, provider provenance, immutable identity and bounded event-window queries. Bootstrap and incremental modes are idempotent and partial provider failure is reported rather than filled synthetically. Coverage exposes true first/latest/count and window coverage separately.

This closes the structural part of CRYPTO-01/YAHOO-01. Historical completeness remains limited by provider lookback, configured bootstrap limits, uptime and initial run. Schema support must not be described as an already populated long history.

## 10. Funding / Basis / Derivatives Contract Audit

Normalized observations include `contract_version`, `rate_kind`, `interval_seconds`, observation/provider timestamps, venue/asset/instrument, sign convention and long/short cashflow semantics, annualization context, and provider lineage. Funding research distinguishes a current indicated rate from realized interval funding. Basis uses mark/index context and durable `basis_observations`; the materializer persists supported BTC/ETH/SOL observations.

Hyperliquid's verified contract is usable for longitudinal reactions. Drift/Velocity contract-v0 remains deliberately excluded/unverified. Consequently:

- **MARKET-01 is PARTIAL, not open and not fully closed.** Ambiguity is removed for v1-supported observations and quarantined for v0, but true cross-venue breadth is incomplete.
- Annualization must use observation interval/rate kind, never the old blanket three-periods-per-day assumption.
- Basis history is forward-only from materializer deployment unless an authoritative backfill is implemented.
- Another venue is not justified until the current corpus has depth and the existing v0 semantics are verified.

## 11. Event Reaction Lab v2 Audit

The single-event service now selects a durable event and bounded market/derivatives windows, reports availability/maturity, calculates price returns, normalized funding/basis changes, regime paths, and linked decisions, and returns observation provenance. The API and frontend are wired. BLOCK outcomes are explicitly counterfactual market movements, never realized P&L. All outputs remain proposal/research-only and non-causal.

The old “single-event only” limitation is closed by the separate multi-event service. The single-event view remains useful for inspection and should not itself be overloaded with statistical claims.

## 12. Multi-Event Statistical Validation Audit

Implemented and verified:

- candidate, included, excluded, matured and observed n;
- observed/matured-non-overlap coverage denominator and reconciled missingness taxonomy;
- chronological horizon-specific overlap exclusion;
- event time-basis/type/family strata;
- raw values, mean, median, quantiles, IQR and sample standard deviation;
- versioned winsorized sensitivity without replacing raw estimates;
- deterministic descriptive bootstrap intervals with low-n unavailability;
- low-sample and multiple-comparison/non-causal disclosures;
- funding direction/sign-flip and basis premium/discount transitions;
- regime transition matrices with the same horizon overlap policy;
- decision ALLOW/BLOCK classifications, link-type/regime/event strata and complete-cohort governance;
- bounded source queries and stable sample hashes.

No p-values are necessary now. The remaining risks are observational: survivorship/provider availability, source contract changes, clustered or near-duplicate events, unequal weekend/session coverage, authority-class mixing, forward-only derivatives, and censored decisions. These deserve diagnostic sensitivity once n is large enough, not premature inferential machinery.

## 13. Event-Time / Overlap / Sample Integrity Audit

All 21 requested PR #50 checks are present:

1. Event iteration does not overwrite the source event row with observation rows.
2. Candidate/included/excluded counts derive from real event rows.
3. Price retrieval uses event-target bounds, not a latest-10,000 slice.
4. Funding retrieval uses event-target bounds, not a latest-1,000 slice.
5. Basis retrieval uses event-target bounds, not a latest-1,000 slice.
6. Bounds derive from event reference times and maximum horizon.
7. Dataset first/latest coverage is distinct from returned query-window coverage.
8. `event_predates_dataset` uses actual dataset coverage.
9. `results_by_event_time_basis` is populated.
10. Mixed-basis headline statistics are suppressed with a direction to strata.
11. `results_by_event_type` is populated.
12. `results_by_event_family` is populated.
13. Regime statistics use horizon overlap filtering.
14. Funding direction and sign-flip counts/rates exist.
15. Basis premium→discount and discount→premium transitions exist.
16. Decision statistics include actual realized and counterfactual classifications.
17. BLOCK is explicitly counterfactual market move, not realized P&L.
18. Explicit links require immutable recorded evidence in decision data.
19. Temporal-only links retain `temporal_proximity_only` labels.
20. Truncated decision cohorts suppress complete-cohort statistics.
21. Pure, service and API behavioral tests exercise these paths.

The integrity contract is unusually strong for descriptive research. It prevents a bounded query from manufacturing an apparent dataset start and prevents mixed time definitions from producing a misleading headline.

## 14. Decision / Regime Linkage Audit

Event-linked regimes use governed historical snapshots and transition matrices rather than current-state substitution. Decision association distinguishes an immutable recorded event reference from temporal proximity. Aggregates expose counts/classifications and strata by link type, regime signature, event type and family. Complete-cohort statistics fail closed when the bounded decision query reports truncation.

An ALLOW outcome can have realized execution/P&L semantics only where the durable order/fill record supports it. A BLOCK has no fill and remains a counterfactual market-move classification. That distinction is correctly carried into API methodology and UI copy.

## 15. Price Authority / Price Integrity Audit

### A. Execution authority

`PriceAuthority.get_price()` still selects the first positive cached candidate in Pyth→Kraken→CoinGecko order (Yahoo is explicit research-only opt-in). Deterministic priority-first authority is acceptable as an execution design **if** freshness and cross-source integrity gates are independent and fail closed. There is no evidence in this audit that a median should silently replace the chosen venue/oracle reference.

### B. Diagnostics and safety

The validator compares available venues, returns `UNKNOWN` when evidence is insufficient and `WARNING` above deviation thresholds. PRs #44/#45 isolate state by asset. Readiness checks age and integrity for BTC/ETH/SOL; live execution requires fresh data and `OK`, including fail-closed UNKNOWN behavior.

The remaining gap is explanatory diagnostics: per-source ages, pairwise/median deviation, usable-source count, quorum reason, rejected outliers, confidence and history of status changes should be consolidated and visible. Add these **before** debating selection redesign. PRICE-01 is therefore PARTIAL and PRICE-02 captures the diagnostic product gap.

## 16. Geopolitical Evidence Quality Audit

| Domain | Current evidence class | Assessment |
|---|---|---|
| Sanctions | **authoritative observed** | Official OFAC evidence with durable changes; strong but US-jurisdiction-specific. |
| Trade policy | **authoritative observed / evidence-supported proxy** | WITS observations and WTO evidence are authoritative for their published series; update time is not always legal-event time. |
| Conflict | **observed but non-authoritative / proxy** | GDELT tone/volume observes media, not a verified conflict-event ledger. |
| Shipping/chokepoints | **evidence-supported proxy / static mapping** | mappings contextualize exposure but do not prove a disruption. |
| Energy shocks | **evidence-supported proxy / scenario** | market/geopolitical context exists; no authoritative physical supply/production event feed. |
| Commodity shocks | **proxy / scenario** | market mappings and scenarios, not a broad durable observed commodity-shock corpus. |
| Cyber/policy | **static mapping / scenario only** | no authoritative normalized observed event history. |
| Macro controls | **scenario only / current derived context** | no durable FRED-like macro-control panel aligned to event windows. |

Strong OFAC coverage must not mask this imbalance. Of evaluated additions, **GDELT Events** adds the highest unique immediate research value because it can populate observed conflict/policy event candidates in the exact durable event-study architecture. It is non-authoritative and requires deduplication, source-class labels and clustering controls. EIA is the best later authoritative addition for energy shocks; FRED is valuable later for macro controls; UN Comtrade largely overlaps current trade emphasis; more sanctions jurisdictions add authority but less domain breadth; another derivatives provider adds little until present history is deep.

## 17. Historical Data Depth Audit

| Table | Longitudinal schema | Population/backfill reality | Current constraint |
|---|---|---|---|
| `research_events` | Strong | OFAC/WITS persist forward; historical event backfill is source/policy-dependent | event-family breadth and n |
| `research_market_bars` | Strong | bounded bootstrap plus incremental BTC/ETH/SOL | provider lookback, uptime, gaps |
| `funding_ticks` | Strong v1; v0 isolated | verified materialization mainly forward; unsupported old contracts cannot be promoted | venue/era availability bias |
| `basis_observations` | Strong | forward from materializer unless backfilled | shallowest derivatives series |
| `regime_snapshots` | Adequate | scheduled forward history | pre-deployment regimes absent/sparse |
| `decision_audit` | Strong immutable ledger | forward from audited decision boundary | selection/censoring; not all events have decisions |
| `market_ticks` | Operational history | runtime cadence/retention, not primary event-bar corpus | uneven sessions/retention |
| `stablecoin_ticks` | Adequate | scheduled forward accumulation | sparse historical stress episodes |
| `index_history` | Adequate | scheduled forward accumulation | limited historical tariff/shock regimes |

The likely sample-constrained studies are basis reactions first, funding/provider strata second, non-sanctions/non-trade event families, long horizons (7d), decision link-type/type/family subgroups, rare regime transitions and stablecoin stress. Bootstrap availability does not manufacture power; low-n suppression is correct.

## 18. Provenance / Data Quality Audit

Provider-native identity, ingest run, observed/provider/ingested times, evidence references, contract versions and coverage/missingness are strong for newly added research tables. Query integrity describes requested bounds, returned bounds and global coverage. Unsupported provider contracts are isolated rather than guessed.

Remaining limitations are transformation artifact durability, source-era drift, and operational alerting. A computed response is reproducible from sample hashes/policies while the underlying immutable rows remain available, but it is not itself a signed/persisted research report. Do not build a new artifact platform until users need durable report citations.

## 19. Frontend / Backend Capability Alignment

| Backend capability | UI state | Detail |
|---|---|---|
| headline price/funding/basis medians | **VISIBLE** | matrix/scalar summaries |
| included/candidate sample counts and time-basis labels | **PARTIALLY VISIBLE** | no full matured/observed/excluded reconciliation |
| missingness and overlap | **PARTIALLY VISIBLE** | raw JSON in details rather than interpretable table |
| regime results | **PARTIALLY VISIBLE** | raw JSON, not coverage/transition visualization |
| decision statistics | **PARTIALLY VISIBLE** | candidate/included/truncated text; classifications are hidden |
| `results_by_event_time_basis` | **HIDDEN** | crucial when headline is suppressed |
| `results_by_event_type` / `results_by_event_family` | **HIDDEN** | no subgroup explorer |
| `stratification_metadata` | **HIDDEN** | subgroup warnings/policy not rendered |
| funding direction/sign-flip counts | **HIDDEN** | only median delta is rendered |
| basis premium/discount transition counts | **HIDDEN** | only median delta is rendered |
| regime coverage/overlap details | **PARTIALLY VISIBLE** | raw details only |
| decision realized/counterfactual classification statistics | **HIDDEN** | only BLOCK warning visible |
| `results_by_link_type` / `results_by_regime_signature` | **HIDDEN** | no structured decision drilldown |
| decision type/family strata | **HIDDEN** | not rendered |
| `data_query_integrity` | **HIDDEN** | user cannot inspect actual vs requested/global bounds |

**Yes: Complete Multi-Event Statistical Research UX is the highest-value immediate feature.** It makes already-correct work usable and truth-auditable without adding a provider, schema, statistic, or top-level tab. It should remain a rendering/composition PR and must preserve low-n/mixed-basis suppression.

## 20. Security Audit

SEC-01 remains open. Middleware protects a manually maintained set of exact paths and regex patterns. All other requests—including an accidentally unlisted POST/PUT/PATCH/DELETE external mutation—default allow. Calculation/research POSTs (scenario, preview, stress, replay, sensitivity) correctly need not require operator credentials merely because they use POST, so blanket method blocking would be incorrect.

Focused auth/readiness tests verify known routes and token/gate behavior, but there is no exhaustive application-route inventory test forcing every mutating route to be classified as `external_state_mutation` or `calculation_only`. The smallest safe improvement is explicit route metadata or a centralized classification registry, a startup/test inventory assertion, and default-deny operator auth for the external-state class. Do not implement a broader identity platform now.

## 21. Tests / CI / Reproducibility Audit

- `pyproject.toml` declares Python `>=3.11` and dependencies; `uv.lock` provides a concrete lock for uv-based installation.
- README setup supports installing/running locally, but broad lower bounds alone are not reproducibility; `uv sync --frozen` is the reproducible path.
- No `.github/workflows` files exist. Pytest, compile checks and Node syntax checks do not automatically run on PRs.
- Explicitly supported upper Python range/matrix is absent.
- PostgreSQL/Redis behaviors are frequently mocked/faked; no CI service workflow proves migrations and integration behavior against pinned services.
- New statistical/service/API tests are behavioral and valuable. A material residue of frontend/alignment tests still searches source strings, which can pass without browser behavior.

GitHub CI is now a meaningful P1 priority because the suite is large and cross-layer. Keep it simple: locked install, supported Python version(s), pytest, compile, three Node checks, and explicit integration markers/services. Do not add Kubernetes or an observability stack.

## 22. Production / Execution Readiness Audit

1. **Strong research/paper system? Yes.** It is deterministic, provenance-conscious, missing-data truthful, historically bounded, auditable and increasingly longitudinal.
2. **Production-ready for real capital? No.** Prototype venue adapters and repository documentation correctly say so.
3. **Before capital:** default-deny mutation classification; mature price diagnostics and incident thresholds; venue signing/conformance tests; idempotent reconciliation against venue truth; robust partial fill and cancel/replace state machines; restart/venue-disconnect recovery; secret rotation/storage practice; monitoring/SLOs/alerts; operator runbooks and kill-switch drills; fault injection; pinned CI/integration tests; and controlled paper/canary evidence.

Execution gates, paper default, independent live enablement, immutable final decision, readiness, idempotency, durable orders/fills and conservative UNKNOWN handling are good foundations. They do not substitute for venue conformance and operational recovery. Research maturity must not be used to justify live trading.

## 23. Product Goal Alignment Scorecard V2

| Dimension | Score | Status | What exists | What remains |
|---|---:|---|---|---|
| Tariff Data & Trade Policy Intelligence | 84 | Strong | WITS/WTO, truthful observed aggregation, durable events | deeper legal-effective event history |
| Geopolitical Evidence Quality | 66 | Developing | evidence classes, OFAC, GDELT proxy, durable events | observed conflict/shipping/energy breadth |
| Authoritative Sanctions Intelligence | 92 | Strong | official OFAC, restart-safe immutable deltas | jurisdictions beyond OFAC |
| Crypto Spot Current Coverage | 91 | Strong | canonical BTC/ETH/SOL multi-source state | richer diagnostic history |
| Crypto Spot Historical Coverage | 82 | Strong architecture | durable bars, bootstrap, coverage, bounded queries | demonstrated deep populated corpus |
| Crypto Perpetual / Funding Coverage | 78 | Good | verified normalized Hyperliquid BTC/ETH/SOL | verified Drift/Velocity and depth |
| Perpetual Basis Coverage | 74 | Good architecture | durable materialized normalized basis | backward depth/provider breadth |
| Cross-Venue Derivatives Comparability | 62 | Limited | contract versioning and v0 quarantine | two or more verified comparable venues |
| Event → Market Reaction Research | 91 | Strong | v2 price/derivative/regime/decision chain | deeper event evidence/n |
| Multi-Event Statistical Validation | 90 | Strong | governed descriptive statistics and strata | bias sensitivities and populated n |
| Historical Data Depth | 66 | Developing | longitudinal schemas and bounded bootstrap | sustained/backfilled representative history |
| Regime Analytics | 84 | Strong | durable snapshots, governed transitions | rare-state sample depth |
| Trading Decision Evaluation | 88 | Strong | immutable audit, replay, outcomes | production venue evidence |
| Event-Linked Decision Evaluation | 86 | Strong | explicit/temporal links, cohort integrity, strata | larger complete cohorts |
| Counterfactual Research | 90 | Strong | immutable-baseline research replay, honest BLOCK semantics | empirical validation depth |
| Risk / Execution Research | 86 | Strong research | deterministic gates, paper simulations, risk controls | venue conformance/operations |
| Provenance & Auditability | 89 | Strong | run/evidence/contract/sample/query lineage | durable derived report artifacts if needed |
| Missing-Data Truthfulness | 94 | Excellent | explicit unavailable/maturity/reasons/coverage | operational alerts |
| Frontend Research Usability | 70 | Functional | Lab v2 and headline statistics | structured PR #50 strata/integrity UX |
| Security Boundary | 62 | Limited | token protection and live gates | default-deny classified mutation inventory |
| Test / CI Reproducibility | 60 | Limited | lockfile, large focused suite | GitHub CI and service integration |
| Production Reliability | 54 | Prototype | readiness, persistence, reconciliation foundations | live adapter/recovery/runbook maturity |

**OVERALL ALIGNMENT SCORE: 79/100.** This is a reasoned product-alignment score, not a mathematical average pretending dimensions have equal weight. Relative to V1's 67, durable event/market/derivatives history (+), Event Reaction Lab v2 (+), multi-event sample governance (+), and asset-scoped integrity (+) justify improvement. The score is capped by actual depth, evidence asymmetry, hidden frontend output, security/CI gaps and non-production venue operations.

## 24. Highest-Value Remaining Gaps

1. **UX truth/access:** governed backend strata and integrity cannot be effectively inspected in the current UI (P0).
2. **Actual evidence/history:** schemas outpace populated depth; conflict/shipping/energy families remain weak (P1).
3. **Price diagnostics:** authority is deterministic but disagreement/freshness evidence is not sufficiently consolidated (P1).
4. **Security:** external mutations default allow unless manually enumerated (P1).
5. **Reproducibility:** no automatic GitHub validation or pinned service integration (P1).
6. **Statistical bias diagnostics:** event duplication/clustering, source eras and session/provider availability need sensitivity once n supports it (P1).

## 25. Recommended PR Roadmap

### PR #52 — Complete Multi-Event Statistical Research UX

- **Priority:** P0; **surface:** frontend primarily, minimal backend only for contract correction; **schema:** none; **blocks later work:** no backend feature, but blocks complete product usability.
- **Problem/why now:** PR #50 produces truthful strata and integrity, but users see coarse summaries/raw JSON. Surfacing existing output gives immediate value without widening architecture.
- **Exact scope:** structured tabs/accordions within the existing Reaction Lab; sample funnel; horizon coverage/missingness/overlap table; time-basis/type/family strata; funding sign flips; basis transitions; regime matrices/coverage; decision classifications/link/regime/type/family strata; query-bound inspector; warnings/empty/low-n/mixed-basis states.
- **Likely files:** `frontend/assets/ui.js`, `frontend/assets/app.js`, `frontend/assets/api.js`, `frontend/assets/styles.css`, `frontend/index.html`; focused UX tests. Extract a small renderer module only if it reduces touch risk.
- **Tests:** rendered semantic states, escaping, hidden/suppressed headline behavior, low-n, truncated cohort, empty strata, API contract fixture, Node syntax.
- **Out of scope:** new statistics, endpoint proliferation, schema, provider, top-level tab, React/framework migration.
- **Dependencies:** merged #50 only.

### PR #53 — Canonical Price Integrity, Freshness & Consensus Diagnostics

- **Priority:** P1; **surface:** backend + frontend; **schema:** none expected; **blocks:** evidence-based authority changes and contributes to live readiness.
- **Problem/why now:** execution authority is defensible, but operators/researchers need explainable source disagreement and freshness.
- **Exact scope:** per-asset usable-source count, ages/timestamps, pairwise/median deviations, configured quorum reason, outlier labels, selected-source context, UNKNOWN/WARNING rationale; read-only endpoint/status panel; keep live fail-closed gates.
- **Likely files:** `backend/core/price_validator.py`, `backend/core/price_authority.py` only for read metadata, `backend/core/readiness.py`, `backend/api/markets_routes.py`, state keys if necessary, frontend market/quality renderer, focused tests.
- **Tests:** stale source, one-source UNKNOWN, disagreement WARNING, asset isolation, selected price unchanged, live block behavior.
- **Out of scope:** median execution authority, automated venue switching, schema/history, live rollout.
- **Dependencies:** none.

### PR #54 — Default-Deny External Mutation Authorization

- **Priority:** P1; **surface:** backend-only; **schema:** none; **blocks:** safe new mutations/live deployment.
- **Problem/why now:** exact path lists are omission-prone while calculation POSTs legitimately remain public.
- **Exact scope:** explicit external-mutation vs calculation-only classification; startup or test inventory of all POST/PUT/PATCH/DELETE routes; default deny/auth for external mutations; preserve independent Jupiter gate.
- **Likely files:** `backend/core/operator_auth.py`, `main.py`, router declarations/metadata, `tests/test_operator_auth.py`, `tests/test_production_readiness.py`.
- **Tests:** exhaustive inventory, unknown external mutation denied, research POST public, token failures, route parameters, live configuration.
- **Out of scope:** OAuth/RBAC/user accounts, frontend auth redesign, secret manager, execution changes.
- **Dependencies:** none.

### PR #55 — Reproducible GitHub CI & Validation Workflow

- **Priority:** P1; **surface:** repository/tooling; **schema:** none; **blocks:** dependable multi-contributor delivery, not #52.
- **Problem/why now:** lock exists but nothing enforces it or runs the growing suite on PRs.
- **Exact scope:** GitHub Actions PR/push workflow; `uv sync --frozen`; documented supported Python matrix; pytest; compileall; Node checks; clear PostgreSQL/Redis integration markers or pinned services; cache without weakening lock enforcement.
- **Likely files:** `.github/workflows/ci.yml`, `pyproject.toml` only for markers/version declaration if needed, README test section.
- **Tests:** workflow commands locally; service-dependent subset if configured.
- **Out of scope:** deployment/CD, containers/Kubernetes, coverage quotas, broad dependency upgrades, application changes.
- **Dependencies:** can follow or run independently of #53/#54.

### PR #56 — Observed Geopolitical Event Expansion with GDELT Events

- **Priority:** P1; **surface:** backend + frontend evidence labels; **schema:** probably **no** core schema change (`research_events` is adequate), migration only if a verified identity field cannot fit existing contract; **blocks:** broader geopolitical validation.
- **Problem/why now:** event architecture is ready but evidence families are sanctions/trade-heavy.
- **Exact scope:** bounded GDELT Events ingestion for defined conflict/policy families; deterministic event identity; near-duplicate/clustering rules; source authority label; event times; backfill ceiling; provenance; coverage; opt-in family filters.
- **Likely files:** new/extended GDELT ingest, source registry, research event repository/service filters, scheduler wiring, evidence/UI labels, provider/service tests.
- **Tests:** idempotency, pagination/bounds, duplicate cluster behavior, event-time basis, provider failure, provenance, non-authoritative label, no false causal language.
- **Out of scope:** GDELT tone as authoritative fact, causal inference, unlimited backfill, EIA/FRED, new ML, provider bundle.
- **Dependencies:** CI strongly preferred; PR #52 helps inspection but is not a data dependency.

**Candidate ordering:** A (#52) → B (#53) → C (#54) → D (#55) → E (#56) → F (EIA, later P2) → G (FRED, later P2). Security and CI are higher safety/reliability priorities than GDELT, even though #52 is the highest-value immediate feature. EIA outranks FRED after GDELT because it fills a more direct verified energy-shock evidence gap.

## 26. What NOT To Build Yet

All remain premature: microservices, Kafka, React/framework migration, new ML models, self-modifying agents, autonomous heuristic retuning, causal inference, production live execution, options analytics, DeFi expansion, NFT analytics, many additional venues, another dashboard top-level tab, huge provider expansion, and statistical-significance hunting. Also premature are a new report-artifact platform, broad auth identity/RBAC, and replacing PriceAuthority without diagnostic evidence.

Use current internal boundaries; deepen evidence and samples; make governed results visible; secure/classify mutations; automate validation. One bounded provider at a time is preferable to breadth that creates ungoverned missingness and incompatible eras.

## 27. Final Verdict

The PR #41–#50 roadmap **succeeded**: it closed the architectural blockers identified after PR #39 and produced a durable, statistically governed research system. It did not—and could not through schema/code alone—guarantee a deep representative corpus. The platform is credible for longitudinal, descriptive, non-causal research and paper decision evaluation. It is not production-live-trading ready.

**READY FOR NEXT FEATURE PR.** The exact reasoning is that no broken P0 correctness issue was found in PR #50's sample contract; the highest immediate feature, PR #52, only exposes already-governed backend truth and changes no schema/production decision logic. PRICE-02, SECURITY-02 and CI-01 must follow before expanding mutation/live ambitions. DATADEPTH-01/GEO-02 then bind the strength of empirical conclusions.

# What Should Be Built After Audit V2?

1. **What should PR #52 be?** Complete Multi-Event Statistical Research UX.
2. **Is it the highest-value immediate next feature?** Yes.
3. **Exactly what is hidden?** `results_by_event_time_basis`, `results_by_event_type`, `results_by_event_family`, `stratification_metadata`, full candidate/matured/observed/excluded funnels, funding direction/sign-flip counts, basis premium/discount transitions, structured regime coverage/transitions, decision realized/counterfactual classification statistics, `results_by_link_type`, `results_by_regime_signature`, decision event-type/family strata, and `data_query_integrity`; missingness/overlap and regimes are only partly visible as raw JSON.
4. **Is a higher-priority issue blocking it?** No broken correctness/security issue blocks a read-only frontend PR. Security and CI are urgent next hardening, not reasons to hide completed research.
5. **Redesign PriceAuthority or diagnostics first?** Diagnostics first; retain deterministic priority until evidence supports redesign.
6. **Is SEC-01 open?** Yes.
7. **Default-deny mutation auth near term?** Yes, PR #54, applied to explicitly classified external mutations rather than every POST.
8. **Is GitHub CI meaningful now?** Yes, PR #55.
9. **Largest research-data gap?** Representative observed event depth across conflict/shipping/energy plus matched derivatives history; basis is particularly forward-shallow.
10. **Largest category?** More historical depth and better event evidence—not more statistics.
11. **Add GDELT Events next?** After UX, price, auth and CI; yes as the first bounded evidence expansion.
12. **Add EIA next?** Later, as the highest-authority focused energy follow-up.
13. **Add FRED next?** Later than EIA; useful for macro controls, not the immediate binding event gap.
14. **Do current providers exceed engine needs?** In breadth, largely yes; in authoritative event-family depth and comparable history, no.
15. **Another derivatives venue now?** No. Deepen current verified contracts and resolve Drift/Velocity semantics first.
16. **Another ML model now?** No.
17. **Causal inference now?** No; event authority, depth, clustering and controls are insufficient.
18. **Live execution hardening now?** Necessary before any live-capital plan, but not justified as the next product feature; keep paper default.
19. **Frontend framework migration?** No.
20. **Monolith?** Keep the modular monolith; extract internal services/renderers when touched.
21. **Next five PRs in order?** #52 UX; #53 price diagnostics; #54 mutation security; #55 CI; #56 GDELT Events.
22. **Priorities?** #52 P0; #53–#56 P1. Later EIA/FRED are P2 until corpus/usage evidence changes priority.
23. **Frontend-only?** #52 should be frontend-primary and can be frontend-only if the existing API fixture is sufficient.
24. **Backend-only?** #54; #55 is tooling rather than product backend.
25. **Backend + frontend?** #53 and #56.
26. **Schema changes?** None definitely. #56 should reuse `research_events`; add a migration only on demonstrated identity-contract need.
27. **Explicitly no schema?** #52, #53, #54 and #55.
28. **Overbuilding?** Microservices/Kafka/React, provider bundles, new ML/agents, p-value hunting, causal claims, options/DeFi/NFT breadth, many venues, or live execution before operational proof.
29. **Shift from foundations?** Yes—toward evidence depth, governed UX and validation, while completing bounded security/CI hardening.
30. **Single highest-value next PR?** PR #52, Complete Multi-Event Statistical Research UX.

## Validation Record

- `git diff --check`: passed.
- `git status --short` / `git diff --name-only`: only `AUDIT_REPORT_V2.md` was added; historical audits and production/test files were unchanged.
- `.venv/bin/python -m pytest -q`: **487 passed, 4 skipped**.
- `python -m compileall -q backend tests`: passed with the environment default Python.
- `node --check frontend/assets/api.js`, `node --check frontend/assets/app.js`, and `node --check frontend/assets/ui.js`: passed.
- `python -m pytest -q` with the environment default interpreter could not collect because project dependencies were absent from that interpreter; the repository `.venv` contained the locked dependencies and completed the suite as recorded above.
- `git fetch origin main --prune`: environment warning—network CONNECT tunnel returned HTTP 403. The audited SHA is the locally available main-equivalent tip and matches the supplied last-verified baseline; this limitation is stated rather than presenting the fetch as successful.
