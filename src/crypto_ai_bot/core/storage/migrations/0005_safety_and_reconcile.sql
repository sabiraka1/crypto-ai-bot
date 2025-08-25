-- Лок для single-instance
CREATE TABLE IF NOT EXISTS locks (
    app TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL
);

-- Heartbeats компонентов (пригодится для /status расширенного)
CREATE TABLE IF NOT EXISTS heartbeats (
    component TEXT PRIMARY KEY,
    last_beat_ms INTEGER NOT NULL,
    status TEXT
);

-- Журнал результатов reconciliation (по желанию можно писать отчёты)
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    details TEXT
);
