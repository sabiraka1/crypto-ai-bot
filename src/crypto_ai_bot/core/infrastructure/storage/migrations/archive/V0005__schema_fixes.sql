-- V0005__schema_fixes.sql
-- Выравнивание схемы под фактический код (trades, audit_log, idempotency_keys unique)

-- 1) trades: добавляем недостающие колонки
ALTER TABLE trades ADD COLUMN broker_order_id TEXT;
ALTER TABLE trades ADD COLUMN client_order_id TEXT;
ALTER TABLE trades ADD COLUMN status TEXT DEFAULT 'closed';
ALTER TABLE trades ADD COLUMN created_at_ms INTEGER NOT NULL DEFAULT 0;

-- 2) audit_log: таблица, которую использует код (оставляем audit как есть)
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  payload TEXT NOT NULL,
  ts_ms INTEGER NOT NULL
);

-- опциональная мягкая миграция из legacy "audit" (если была)
INSERT INTO audit_log(action, payload, ts_ms)
SELECT topic AS action, payload, ts_ms FROM audit
WHERE NOT EXISTS (
  SELECT 1 FROM audit_log a2 WHERE a2.ts_ms = audit.ts_ms AND a2.action = audit.topic
);

-- 3) idempotency: обеспечиваем уникальность по ключу
CREATE UNIQUE INDEX IF NOT EXISTS ux_idemp_keys_key ON idempotency_keys(key);
