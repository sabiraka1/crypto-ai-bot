-- 0005_decisions.sql
-- Храним последние решения для объяснимости и аналитики

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    decided_ms   INTEGER NOT NULL,         -- UTC epoch millis
    action       TEXT    NOT NULL,         -- buy|reduce|close|hold
    size         TEXT    NOT NULL,         -- Decimal → str
    sl           TEXT    NULL,
    tp           TEXT    NULL,
    trail        TEXT    NULL,
    score        REAL    NULL,
    explain      TEXT    NULL              -- JSON (строка)
);

CREATE INDEX IF NOT EXISTS idx_decisions_symbol_tf_ms
    ON decisions(symbol, timeframe, decided_ms DESC);

CREATE INDEX IF NOT EXISTS idx_decisions_ms
    ON decisions(decided_ms DESC);
