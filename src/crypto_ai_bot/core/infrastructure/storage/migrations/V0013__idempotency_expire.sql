-- V0013: Исправление таблицы идемпотентности и добавление TTL

-- Создаем правильную таблицу idempotency если её нет
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL,
    expire_at INTEGER NOT NULL DEFAULT 0
);

-- Мигрируем данные из старой таблицы если она существует
INSERT OR IGNORE INTO idempotency(key, ts_ms, expire_at)
SELECT key, created_at_ms, expires_at_ms
FROM idempotency_keys
WHERE key IS NOT NULL;

-- Индексы для idempotency
CREATE UNIQUE INDEX IF NOT EXISTS ux_idempotency_key ON idempotency(key);
CREATE INDEX IF NOT EXISTS idx_idempotency_expire ON idempotency(expire_at);
CREATE INDEX IF NOT EXISTS idx_idempotency_ts ON idempotency(ts_ms);

-- Удаляем старую таблицу (опционально, можно оставить для истории)
-- DROP TABLE IF EXISTS idempotency_keys;