-- 0003_idempotency_indexes.sql
-- индексы для идемпотентности (наша таблица: idempotency_keys)
CREATE UNIQUE INDEX IF NOT EXISTS idx_idemkeys_key     ON idempotency_keys(key);
CREATE        INDEX IF NOT EXISTS idx_idemkeys_created ON idempotency_keys(created_at_ms);
