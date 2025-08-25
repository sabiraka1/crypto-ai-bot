-- Базовые таблицы
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,               -- 'buy' | 'sell'
    price REAL NOT NULL,
    amount REAL NOT NULL,             -- base qty
    cost REAL NOT NULL,               -- quote cost (с комиссией, если считаем)
    fee REAL DEFAULT 0,
    fee_currency TEXT DEFAULT 'USDT',
    ts_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    base_qty REAL NOT NULL DEFAULT 0,
    average_price REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket_ms INTEGER NOT NULL,
    key TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    topic TEXT NOT NULL,
    level TEXT NOT NULL,
    payload TEXT
);
