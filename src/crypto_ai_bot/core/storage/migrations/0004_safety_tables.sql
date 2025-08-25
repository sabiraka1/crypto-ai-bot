-- Локи для single-instance
CREATE TABLE IF NOT EXISTS locks (
    app TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL
);
