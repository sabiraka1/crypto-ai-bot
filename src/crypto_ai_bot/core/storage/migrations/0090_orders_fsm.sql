BEGIN;

-- trades: добавляем поля для FSM и комиссий (аддитивно, совместимо)
ALTER TABLE trades ADD COLUMN order_id TEXT;
ALTER TABLE trades ADD COLUMN state TEXT DEFAULT 'filled';
ALTER TABLE trades ADD COLUMN fee_amt REAL DEFAULT 0.0;
ALTER TABLE trades ADD COLUMN fee_ccy TEXT DEFAULT 'USDT';

-- таблица защитных выходов (soft SL/TP)
CREATE TABLE IF NOT EXISTS protective_exits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,        -- 'sell' (long-only выходы)
  kind TEXT NOT NULL,        -- 'sl' | 'tp'
  trigger_px REAL NOT NULL,
  created_ts INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

COMMIT;
