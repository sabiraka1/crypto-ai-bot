-- trades, positions, snapshots, audit (без идемпотентности)
CREATE TABLE IF NOT EXISTS trades (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('buy','sell')),
    amount          TEXT NOT NULL,           -- Decimal в текстовом виде
    price           TEXT NOT NULL,
    cost            TEXT NOT NULL,
    fee_currency    TEXT NOT NULL,
    fee_cost        TEXT NOT NULL,
    ts              INTEGER NOT NULL,
    client_order_id TEXT,
    meta_json       TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    symbol          TEXT PRIMARY KEY,
    size            TEXT NOT NULL,           -- Decimal в текстовом виде
    avg_price       TEXT NOT NULL,
    updated_ts      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    ts              INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL,
    symbol          TEXT,
    side            TEXT,
    amount          TEXT,
    price           TEXT,
    fee             TEXT,
    client_order_id TEXT,
    ts              INTEGER NOT NULL,
    payload_json    TEXT,
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')*1000)
);
