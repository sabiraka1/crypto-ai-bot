-- src/crypto_ai_bot/core/storage/migrations/versions/0003_add_idempotency.sql
BEGIN;

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL,              -- 'claimed' | 'committed'
  created_at INTEGER NOT NULL,      -- epoch seconds
  ttl_seconds INTEGER NOT NULL,
  payload TEXT
);

CREATE INDEX IF NOT EXISTS ix_idem_state ON idempotency_keys(state);

COMMIT;
