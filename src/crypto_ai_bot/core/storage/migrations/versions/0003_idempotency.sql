-- src/crypto_ai_bot/core/storage/migrations/versions/0003_idempotency.sql
BEGIN;

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  created_at_ms INTEGER NOT NULL,
  ttl_seconds INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency (expires_at_ms);

COMMIT;
