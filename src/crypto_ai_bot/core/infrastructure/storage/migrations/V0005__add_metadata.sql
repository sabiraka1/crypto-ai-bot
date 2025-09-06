-- V0005: Добавление JSON полей для метаданных

ALTER TABLE trades ADD COLUMN metadata_json TEXT;
ALTER TABLE positions ADD COLUMN metadata_json TEXT;

-- Создаем таблицу для отслеживания изменений позиций
CREATE TABLE IF NOT EXISTS position_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL, -- 'open', 'increase', 'decrease', 'close'
    amount REAL NOT NULL,
    price REAL NOT NULL,
    ts_ms INTEGER NOT NULL,
    trace_id TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_position_history_symbol ON position_history(symbol);
CREATE INDEX IF NOT EXISTS idx_position_history_ts ON position_history(ts_ms);