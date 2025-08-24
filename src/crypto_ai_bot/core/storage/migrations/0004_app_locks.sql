-- 0004_app_locks.sql
BEGIN;

CREATE TABLE IF NOT EXISTS app_locks (
    app TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL
);

COMMIT;
