-- Таблицы безопасности и журнала сверок

CREATE TABLE IF NOT EXISTS app_locks (
    app TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expire_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- orders | positions | balances
    symbol TEXT NOT NULL,
    details TEXT NOT NULL        -- json
);

CREATE INDEX IF NOT EXISTS idx_recon_ts ON reconciliation_log(ts_ms);
CREATE INDEX IF NOT EXISTS idx_recon_kind ON reconciliation_log(kind);