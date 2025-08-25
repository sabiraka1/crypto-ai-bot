-- Индексы идемпотентности
CREATE INDEX IF NOT EXISTS idx_idemp_bucket_key ON idempotency_keys(bucket_ms, key);
CREATE INDEX IF NOT EXISTS idx_idemp_expires ON idempotency_keys(expires_at_ms);
