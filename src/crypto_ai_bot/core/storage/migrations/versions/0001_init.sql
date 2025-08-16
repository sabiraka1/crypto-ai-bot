-- positions, trades, snapshots, audit_log, idempotency_keys
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS positions (
  id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,                 -- buy|sell
  size_base TEXT NOT NULL,            -- Decimal as TEXT
  entry_price TEXT NOT NULL,          -- Decimal as TEXT
  sl TEXT NULL,
  tp TEXT NULL,
  opened_at INTEGER NOT NULL,         -- ms
  status TEXT NOT NULL,               -- open|closed
  updated_at INTEGER NOT NULL,        -- ms
  realized_pnl TEXT NOT NULL DEFAULT '0' -- Decimal as TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol_status ON positions(symbol, status);

CREATE TABLE IF NOT EXISTS trades (
  id TEXT PRIMARY KEY,
  position_id TEXT NULL REFERENCES positions(id) ON DELETE SET NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  type TEXT NOT NULL,
  amount_base TEXT NOT NULL,          -- Decimal as TEXT
  price TEXT NOT NULL,                -- Decimal as TEXT
  fee_quote TEXT NOT NULL DEFAULT '0',-- Decimal as TEXT
  fee_currency TEXT NOT NULL,
  timestamp INTEGER NOT NULL,
  client_order_id TEXT UNIQUE NULL,
  extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  taken_at INTEGER NOT NULL,
  payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(taken_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NULL,
  details TEXT,
  idempotency_key TEXT UNIQUE NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
