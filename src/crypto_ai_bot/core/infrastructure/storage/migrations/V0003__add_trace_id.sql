-- V0003: Добавление trace_id для корреляции операций
-- Критично для отслеживания всех операций в рамках одного цикла

ALTER TABLE trades ADD COLUMN trace_id TEXT;
ALTER TABLE audit ADD COLUMN trace_id TEXT;

-- Создаем таблицу risk_counters если её еще нет
CREATE TABLE IF NOT EXISTS risk_counters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT NOT NULL,
    symbol TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    ts_ms INTEGER NOT NULL,
    trace_id TEXT
);

-- Индексы для быстрого поиска по trace_id
CREATE INDEX IF NOT EXISTS idx_trades_trace_id ON trades(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON audit(trace_id);
CREATE INDEX IF NOT EXISTS idx_risk_counters_trace_id ON risk_counters(trace_id);