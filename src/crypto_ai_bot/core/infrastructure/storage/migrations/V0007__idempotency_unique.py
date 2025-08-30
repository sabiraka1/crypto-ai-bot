-- Уникальный ключ на идемпотентность (без окон между DELETE/INSERT)
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  expire_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency_key ON idempotency(key);
