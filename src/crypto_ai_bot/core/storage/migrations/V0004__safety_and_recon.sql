-- Single-instance lock
CREATE TABLE IF NOT EXISTS locks (
    app TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL
);

-- Heartbeats компонентов (для расширенного /status и DMS)
CREATE TABLE IF NOT EXISTS heartbeats (
    component TEXT PRIMARY KEY,
    last_beat_ms INTEGER NOT NULL,
    status TEXT
);

-- Лог результатов reconciliation/восстановлений (по желанию писать события)
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    details TEXT
);
