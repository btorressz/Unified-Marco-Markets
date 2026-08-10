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

CREATE TABLE IF NOT EXISTS funding_ticks (
    id SERIAL PRIMARY KEY,
    venue VARCHAR(50) NOT NULL,
    market VARCHAR(50) NOT NULL,
    funding_rate FLOAT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
