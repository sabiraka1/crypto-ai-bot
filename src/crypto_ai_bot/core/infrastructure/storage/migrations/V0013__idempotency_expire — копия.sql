-- V0014: Таблица для отслеживания защитных выходов

CREATE TABLE IF NOT EXISTS protective_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    position_id TEXT NOT NULL,
    exit_type TEXT NOT NULL, -- 'stop_loss', 'trailing_stop', 'take_profit_1', 'take_profit_2'
    trigger_price REAL,
    exit_price REAL,
    amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'triggered', 'executed', 'cancelled'
    order_id TEXT,
    trace_id TEXT,
    metadata_json TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    executed_at_ms INTEGER
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_protective_exits_symbol ON protective_exits(symbol);
CREATE INDEX IF NOT EXISTS idx_protective_exits_status ON protective_exits(status);
CREATE INDEX IF NOT EXISTS idx_protective_exits_position ON protective_exits(position_id);

-- Таблица для DMS (Dead Man's Switch)
CREATE TABLE IF NOT EXISTS dms_state (
    id INTEGER PRIMARY KEY,
    last_ping_ms INTEGER NOT NULL,
    trigger_count INTEGER DEFAULT 0,
    last_trigger_ms INTEGER,
    metadata_json TEXT
);

-- Инициализируем одну запись для DMS
INSERT OR IGNORE INTO dms_state(id, last_ping_ms) VALUES (1, 0);