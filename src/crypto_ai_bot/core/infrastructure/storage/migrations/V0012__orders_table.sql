-- orders table for open orders tracking
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT,
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    amount TEXT NOT NULL,
    filled TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'open',
    ts_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
