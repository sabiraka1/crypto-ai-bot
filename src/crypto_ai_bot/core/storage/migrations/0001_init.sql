## `core/storage/migrations/0001_init.sql`
```sql
-- Начальная схема: идемпотентность, сделки, тики, аудит

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idem_created_at ON idempotency_keys(created_at_ms);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,           -- 'buy' | 'sell'
    amount NUMERIC NOT NULL,      -- base amount
    price NUMERIC NOT NULL,       -- average execution price
    cost NUMERIC NOT NULL,        -- quote spent/received
    status TEXT NOT NULL,         -- 'open' | 'closed' | 'failed'
    ts_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS u_trades_client_oid ON trades(client_order_id);
CREATE INDEX IF NOT EXISTS i_trades_symbol_ts ON trades(symbol, ts_ms);

CREATE TABLE IF NOT EXISTS ticker_snapshots (
    symbol TEXT NOT NULL,
    last NUMERIC NOT NULL,
    bid NUMERIC NOT NULL,
    ask NUMERIC NOT NULL,
    ts_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, ts_ms)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts_ms INTEGER NOT NULL
);