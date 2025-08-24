-- таблица для single-instance лока
CREATE TABLE IF NOT EXISTS locks (
  app TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  acquired_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL
);

-- журнал реконсиляции (агрегат/история)
CREATE TABLE IF NOT EXISTS reconciliation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_ms INTEGER NOT NULL,
  type TEXT NOT NULL,
  discrepancy TEXT,
  resolution TEXT
);
