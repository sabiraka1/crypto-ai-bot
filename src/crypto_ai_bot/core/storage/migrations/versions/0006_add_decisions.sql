-- 0006_add_decisions.sql
-- Таблица для хранения принятых решений (Decision + explain)
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    explain_json TEXT NULL,
    score REAL NULL,
    action TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts_ms);
CREATE INDEX IF NOT EXISTS idx_decisions_sym_tf ON decisions(symbol, timeframe);
