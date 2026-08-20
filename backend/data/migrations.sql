CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(200) NOT NULL,
    payload JSONB DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'events'
          AND column_name = 'id'
          AND data_type <> 'uuid'
    ) THEN
        ALTER TABLE events DROP CONSTRAINT IF EXISTS events_pkey;
        ALTER TABLE events ALTER COLUMN id DROP DEFAULT;
        ALTER TABLE events ALTER COLUMN id TYPE UUID USING gen_random_uuid();
        ALTER TABLE events ALTER COLUMN id SET DEFAULT gen_random_uuid();
        ALTER TABLE events ADD PRIMARY KEY (id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS index_history (
    id SERIAL PRIMARY KEY,
    index_level FLOAT NOT NULL,
    rate_of_change FLOAT NOT NULL DEFAULT 0.0,
    shock_score FLOAT NOT NULL DEFAULT 0.0,
    components JSONB DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_ticks (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    venue VARCHAR(50) NOT NULL,
    price FLOAT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable observed Yahoo bars used only for reproducible research.  This is
-- deliberately separate from market_ticks and never participates in pricing.
CREATE TABLE IF NOT EXISTS research_market_bars (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    provider_symbol VARCHAR,
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT,
    research_grade BOOLEAN NOT NULL DEFAULT TRUE,
    authoritative BOOLEAN NOT NULL DEFAULT FALSE,
    execution_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    ingest_run_id UUID,
    retrieved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, symbol, interval_seconds, ts)
);
CREATE INDEX IF NOT EXISTS idx_research_market_bars_symbol_interval_ts
    ON research_market_bars(symbol, interval_seconds, ts);

CREATE TABLE IF NOT EXISTS funding_ticks (
    id SERIAL PRIMARY KEY,
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    funding_rate FLOAT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS contract_version SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS source_id VARCHAR(100);
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS rate_kind VARCHAR(30);
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS raw_funding_rate DOUBLE PRECISION;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS normalized_funding_rate DOUBLE PRECISION;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS interval_seconds INTEGER;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS long_cashflow_rate DOUBLE PRECISION;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS short_cashflow_rate DOUBLE PRECISION;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS annualized_rate DOUBLE PRECISION;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS provider_timestamp TIMESTAMPTZ;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS timestamp_semantics VARCHAR(100);
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS sign_convention VARCHAR(150);
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS research_only BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS execution_eligible BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE funding_ticks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
-- v1 asymmetric observations may have no honest scalar; legacy rows remain intact.
ALTER TABLE funding_ticks ALTER COLUMN funding_rate DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_funding_ticks_venue_market_ts ON funding_ticks(venue,market,ts DESC);
CREATE INDEX IF NOT EXISTS idx_funding_ticks_provider_ts ON funding_ticks(venue,market,provider_timestamp DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_funding_provider_observation
    ON funding_ticks(venue,market,source_id,rate_kind,provider_timestamp)
    WHERE provider_timestamp IS NOT NULL;

CREATE TABLE IF NOT EXISTS basis_observations (
    id BIGSERIAL PRIMARY KEY, contract_version SMALLINT NOT NULL DEFAULT 1,
    symbol VARCHAR(30) NOT NULL, venue VARCHAR(50) NOT NULL, market VARCHAR(50) NOT NULL,
    spot_source VARCHAR(100) NOT NULL, spot_price DOUBLE PRECISION NOT NULL,
    perp_price DOUBLE PRECISION NOT NULL, basis_bps DOUBLE PRECISION NOT NULL,
    spot_ts TIMESTAMPTZ NOT NULL, perp_ts TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL, retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timestamp_skew_seconds DOUBLE PRECISION NOT NULL, aligned BOOLEAN NOT NULL,
    fresh BOOLEAN NOT NULL, research_only BOOLEAN NOT NULL DEFAULT TRUE,
    execution_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    lineage JSONB NOT NULL DEFAULT '{}', metadata JSONB NOT NULL DEFAULT '{}',
    UNIQUE(venue,market,spot_source,spot_ts,perp_ts)
);
CREATE INDEX IF NOT EXISTS idx_basis_venue_market_observed ON basis_observations(venue,market,observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_basis_symbol_observed ON basis_observations(symbol,observed_at DESC);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    size FLOAT NOT NULL,
    entry_price FLOAT NOT NULL,
    pnl FLOAT NOT NULL DEFAULT 0.0,
    margin FLOAT NOT NULL DEFAULT 0.0,
    liq_price FLOAT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size FLOAT NOT NULL,
    price FLOAT NOT NULL,
    order_type VARCHAR(20) NOT NULL DEFAULT 'limit',
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_index_history_ts ON index_history (ts DESC);
CREATE INDEX IF NOT EXISTS idx_market_ticks_ts ON market_ticks (ts DESC);
CREATE INDEX IF NOT EXISTS idx_market_ticks_venue ON market_ticks (venue);
CREATE INDEX IF NOT EXISTS idx_funding_ticks_ts ON funding_ticks (ts DESC);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions (ts DESC);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ts ON paper_trades (ts DESC);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id SERIAL PRIMARY KEY,
    shock_state VARCHAR(50) NOT NULL,
    funding_regime VARCHAR(50) NOT NULL,
    vol_regime VARCHAR(50) NOT NULL,
    tariff_index FLOAT NOT NULL DEFAULT 0.0,
    price FLOAT NOT NULL DEFAULT 0.0,
    return_4h FLOAT,
    return_24h FLOAT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regime_snapshots_ts ON regime_snapshots (ts DESC);

CREATE TABLE IF NOT EXISTS stablecoin_ticks (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price FLOAT NOT NULL,
    depeg_bps FLOAT NOT NULL DEFAULT 0.0,
    source VARCHAR(50) NOT NULL DEFAULT 'unknown',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stablecoin_ticks_ts ON stablecoin_ticks (ts DESC);

CREATE TABLE IF NOT EXISTS conditional_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue VARCHAR(50) NOT NULL DEFAULT 'paper',
    market VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size FLOAT NOT NULL,
    order_type VARCHAR(30) NOT NULL,
    trigger_price FLOAT,
    limit_price FLOAT,
    trailing_amount FLOAT,
    parent_id UUID,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conditional_orders_status ON conditional_orders (status);

CREATE TABLE IF NOT EXISTS agent_signal_history (
    id SERIAL PRIMARY KEY,
    agent VARCHAR(100) NOT NULL,
    ticker VARCHAR(50),
    signal VARCHAR(100) NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.0,
    realized_outcome FLOAT DEFAULT 0.0,
    payload JSONB DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_signal_history_ts ON agent_signal_history (ts DESC);

-- Durable execution lifecycle. Existing paper_trades/positions remain in place
-- for backward compatibility while new execution paths write normalized records.
CREATE TABLE IF NOT EXISTS order_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id VARCHAR(100) NOT NULL,
    client_order_id VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL UNIQUE,
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size FLOAT NOT NULL,
    order_type VARCHAR(30) NOT NULL,
    price FLOAT,
    strategy_id VARCHAR(100),
    decision_id VARCHAR(100),
    status VARCHAR(30) NOT NULL DEFAULT 'created',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id UUID REFERENCES order_intents(id) ON DELETE SET NULL,
    client_order_id VARCHAR(100) NOT NULL,
    venue_order_id VARCHAR(200),
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size FLOAT NOT NULL,
    order_type VARCHAR(30) NOT NULL,
    price FLOAT,
    execution_mode VARCHAR(20) NOT NULL,
    status VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    intent_id UUID REFERENCES order_intents(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (order_id IS NOT NULL OR intent_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS fills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    venue_fill_id VARCHAR(200),
    size FLOAT NOT NULL,
    price FLOAT NOT NULL,
    fee FLOAT NOT NULL DEFAULT 0.0,
    funding FLOAT NOT NULL DEFAULT 0.0,
    slippage FLOAT NOT NULL DEFAULT 0.0,
    payload JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    fill_id UUID REFERENCES fills(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_intents_created_at ON order_intents (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_intents_client_order_id ON order_intents (client_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_client_order_id ON orders (client_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_order_events_order_ts ON order_events (order_id, ts ASC);
CREATE INDEX IF NOT EXISTS idx_order_events_intent_ts ON order_events (intent_id, ts ASC);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills (order_id);

-- Extend the existing position history rather than replacing it.
ALTER TABLE positions ADD COLUMN IF NOT EXISTS order_id UUID REFERENCES orders(id) ON DELETE SET NULL;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS realized_pnl FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS unrealized_pnl FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS fees FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS funding FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS slippage FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_positions_order_id ON positions (order_id);

-- Extend the existing conditional-order table in place so existing deployments
-- retain their data. OCO siblings share oco_group_id; trigger_key is an
-- idempotency guard used by atomic claims.
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS oco_group_id UUID;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS trigger_key VARCHAR(200);
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS current_trigger_level FLOAT;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS triggered_order_id UUID REFERENCES orders(id) ON DELETE SET NULL;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMPTZ;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
ALTER TABLE conditional_orders ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(100);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conditional_orders_trigger_key
    ON conditional_orders (trigger_key)
    WHERE trigger_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conditional_orders_oco_group
    ON conditional_orders (oco_group_id)
    WHERE oco_group_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conditional_orders_parent
    ON conditional_orders (parent_id)
    WHERE parent_id IS NOT NULL;

-- Durable historical backtest metadata. Historical observations stay in their
-- existing source tables; this table records only run configuration and output.
CREATE TABLE IF NOT EXISTS backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mode VARCHAR(20) NOT NULL DEFAULT 'synthetic',
    strategy VARCHAR(50) NOT NULL,
    venue VARCHAR(50),
    market VARCHAR(50),
    start_ts TIMESTAMPTZ,
    end_ts TIMESTAMPTZ,
    config JSONB NOT NULL DEFAULT '{}',
    data_manifest JSONB NOT NULL DEFAULT '{}',
    metrics JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created_at ON backtest_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_mode ON backtest_runs (mode);

-- Auditable research observations for immutable deterministic heuristic versions.
CREATE TABLE IF NOT EXISTS heuristic_evaluations (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), heuristic_id VARCHAR(100) NOT NULL,
 heuristic_version INTEGER NOT NULL, evaluation_type VARCHAR(30) NOT NULL, action_type VARCHAR(50) NOT NULL,
 expected_direction VARCHAR(20), venue VARCHAR(50) NOT NULL, market VARCHAR(100) NOT NULL, symbol VARCHAR(100),
 decision_ts TIMESTAMPTZ NOT NULL, price_at_decision DOUBLE PRECISION NOT NULL, fired BOOLEAN NOT NULL,
 confidence DOUBLE PRECISION, expected_return DOUBLE PRECISION, context JSONB NOT NULL DEFAULT '{}',
 regime JSONB NOT NULL DEFAULT '{}', outcomes JSONB NOT NULL DEFAULT '{}', primary_horizon VARCHAR(10) NOT NULL,
 primary_return DOUBLE PRECISION, signed_primary_return DOUBLE PRECISION, directional_hit BOOLEAN,
 evaluation_status VARCHAR(30) NOT NULL, missing_context JSONB NOT NULL DEFAULT '[]', source VARCHAR(50) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CONSTRAINT uq_heuristic_opportunity UNIQUE (heuristic_id, heuristic_version, venue, market, decision_ts, primary_horizon),
 CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);
CREATE INDEX IF NOT EXISTS idx_heuristic_eval_rule_window ON heuristic_evaluations (heuristic_id, heuristic_version, decision_ts DESC);
CREATE INDEX IF NOT EXISTS idx_heuristic_eval_market_window ON heuristic_evaluations (venue, market, decision_ts DESC);

-- Durable ingestion audit ledger and generic observation provenance.
CREATE TABLE IF NOT EXISTS ingest_runs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), source_id VARCHAR(100) NOT NULL, provider VARCHAR(100) NOT NULL,
 data_type VARCHAR(100), status VARCHAR(30) NOT NULL, started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
 duration_ms DOUBLE PRECISION, records_received INTEGER NOT NULL DEFAULT 0, records_persisted INTEGER NOT NULL DEFAULT 0,
 fallback_used BOOLEAN NOT NULL DEFAULT FALSE, fallback_source_id VARCHAR(100), fallback_type VARCHAR(50),
 provider_timestamp TIMESTAMPTZ, lease_acquired BOOLEAN, lease_skipped BOOLEAN NOT NULL DEFAULT FALSE, worker_id VARCHAR(200),
 error_type VARCHAR(200), error_message TEXT, metadata JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_source_started ON ingest_runs (source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status_started ON ingest_runs (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs (started_at DESC);
CREATE TABLE IF NOT EXISTS data_provenance (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), ingest_run_id UUID, source_id VARCHAR(100) NOT NULL,
 artifact_type VARCHAR(100) NOT NULL, artifact_id VARCHAR(200), artifact_key VARCHAR(300), provider_timestamp TIMESTAMPTZ,
 received_at TIMESTAMPTZ, persisted_at TIMESTAMPTZ, fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
 fallback_source_id VARCHAR(100), quality JSONB NOT NULL DEFAULT '{}', lineage JSONB NOT NULL DEFAULT '{}',
 metadata JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_provenance_run ON data_provenance (ingest_run_id);
CREATE INDEX IF NOT EXISTS idx_provenance_source_created ON data_provenance (source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provenance_artifact ON data_provenance (artifact_type, artifact_id);
CREATE INDEX IF NOT EXISTS idx_provenance_created ON data_provenance (created_at DESC);

-- Append-only research history, separate from the operational events bus.
CREATE TABLE IF NOT EXISTS research_events (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), event_key VARCHAR(64) UNIQUE NOT NULL,
 event_family VARCHAR(100), event_type VARCHAR(100) NOT NULL, source VARCHAR(100) NOT NULL, source_id VARCHAR(100) NOT NULL,
 authority VARCHAR(300), jurisdiction VARCHAR(100), claim_type VARCHAR(60) NOT NULL,
 observed BOOLEAN NOT NULL, authoritative BOOLEAN NOT NULL, proxy BOOLEAN NOT NULL, synthetic BOOLEAN NOT NULL,
 execution_eligible BOOLEAN NOT NULL, event_timestamp TIMESTAMPTZ, event_time_basis VARCHAR(100),
 published_at TIMESTAMPTZ, effective_at TIMESTAMPTZ, provider_updated_at TIMESTAMPTZ,
 detected_at TIMESTAMPTZ, retrieved_at TIMESTAMPTZ, source_record_id VARCHAR(300),
 source_record_type VARCHAR(100), change_type VARCHAR(40), evidence_contract_version INTEGER,
 transformation VARCHAR(200), transformation_version VARCHAR(50), content_hash VARCHAR(128), dataset_version VARCHAR(128),
 study_eligible BOOLEAN NOT NULL DEFAULT FALSE, payload JSONB NOT NULL DEFAULT '{}', evidence JSONB NOT NULL DEFAULT '{}',
 lineage JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_events_source_time ON research_events(source_id,event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_research_events_family_time ON research_events(event_family,event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_research_events_type_time ON research_events(event_type,event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_research_events_record_time ON research_events(source_record_id,event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_research_events_study_time ON research_events(event_timestamp DESC) WHERE study_eligible=TRUE;

-- Additive, auditable ML registry. Artifacts originate only from local training.
CREATE TABLE IF NOT EXISTS ml_datasets (
 id VARCHAR(64) PRIMARY KEY, dataset_hash CHAR(64) UNIQUE NOT NULL, manifest JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ml_training_runs (
 id UUID PRIMARY KEY, dataset_id VARCHAR(64) NOT NULL REFERENCES ml_datasets(id), status VARCHAR(30) NOT NULL,
 method VARCHAR(60) NOT NULL, fold_metrics JSONB NOT NULL DEFAULT '[]', metrics JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ml_models (
 id UUID PRIMARY KEY, model_key VARCHAR(100) NOT NULL, model_version VARCHAR(30) NOT NULL,
 training_run_id UUID NOT NULL REFERENCES ml_training_runs(id), dataset_id VARCHAR(64) NOT NULL REFERENCES ml_datasets(id),
 model_type VARCHAR(100) NOT NULL, lifecycle_state VARCHAR(20) NOT NULL CHECK (lifecycle_state IN ('candidate','active','archived','rejected')),
 feature_schema_id VARCHAR(100) NOT NULL, feature_schema_version INTEGER NOT NULL, label_definition_id VARCHAR(100) NOT NULL,
 label_definition_version INTEGER NOT NULL, validation_metrics JSONB NOT NULL DEFAULT '{}', calibration_metrics JSONB NOT NULL DEFAULT '{}',
 artifact_blob BYTEA NOT NULL, artifact_sha256 CHAR(64) NOT NULL, library_versions JSONB NOT NULL DEFAULT '{}', promotion_reason TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), promoted_at TIMESTAMPTZ, archived_at TIMESTAMPTZ,
 UNIQUE(model_key,model_version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ml_one_active ON ml_models(model_key) WHERE lifecycle_state='active';
CREATE TABLE IF NOT EXISTS ml_predictions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), input_hash CHAR(64) NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_created ON ml_predictions(created_at DESC);

-- Immutable, compact linkage across decision layers. This stores intent only;
-- it has no relationship to order routing or execution persistence.
CREATE TABLE IF NOT EXISTS decision_audit (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), decision_ts TIMESTAMPTZ NOT NULL,
 decision_type VARCHAR(100) NOT NULL, venue VARCHAR(50), market VARCHAR(100), symbol VARCHAR(100),
 input_state JSONB NOT NULL DEFAULT '{}', input_provenance JSONB NOT NULL DEFAULT '{}',
 derived_state JSONB NOT NULL DEFAULT '{}', heuristic_result JSONB NOT NULL DEFAULT '{}',
 ml_result JSONB NOT NULL DEFAULT '{}', risk_result JSONB NOT NULL DEFAULT '{}',
 allocation_result JSONB NOT NULL DEFAULT '{}', execution_intent JSONB NOT NULL DEFAULT '{}',
 component_versions JSONB NOT NULL DEFAULT '{}', config_snapshot JSONB NOT NULL DEFAULT '{}',
 final_decision JSONB NOT NULL DEFAULT '{}', decision_hash CHAR(64) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decision_audit_ts ON decision_audit(decision_ts DESC);
CREATE INDEX IF NOT EXISTS idx_decision_audit_type_ts ON decision_audit(decision_type, decision_ts DESC);
CREATE INDEX IF NOT EXISTS idx_decision_audit_market_ts ON decision_audit(venue, market, decision_ts DESC);
