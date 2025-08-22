-- 0002_indexes.sql
BEGIN;

-- ускоряем выборки и агрегации
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts       ON trades(symbol, ts_ms);

-- гарантируем уникальность ключа идемпотентности
CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency_key ON idempotency(key);

-- ускоряем очистку по времени
CREATE INDEX IF NOT EXISTS idx_idempotency_created    ON idempotency(created_at_ms);
CREATE INDEX IF NOT EXISTS idx_audit_ts               ON audit(ts_ms);

COMMIT;
