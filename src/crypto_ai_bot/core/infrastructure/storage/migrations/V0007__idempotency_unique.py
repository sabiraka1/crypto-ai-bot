-- V0007__idempotency_unique.sql
-- Назначение: обеспечить уникальность ключа идемпотентности и ускорить очистку по времени.

-- Уникальность ключа идемпотентности
CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_key
    ON idempotency(key);

-- Индекс по времени жизни записи (ускоряет prune по TTL)
-- Если поле ts_ms отсутствует в вашей версии схемы, добавьте его миграцией V0001__init.sql
-- или удалите этот индекс.
CREATE INDEX IF NOT EXISTS idx_idempotency_ts
    ON idempotency(ts_ms);
