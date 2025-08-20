-- 004_add_client_order_id.sql
-- Добавляет колонку client_order_id и индекс для быстрых reconcile-поисков

ALTER TABLE trades ADD COLUMN client_order_id TEXT;

CREATE INDEX IF NOT EXISTS idx_trades_client_order_id ON trades(client_order_id);
