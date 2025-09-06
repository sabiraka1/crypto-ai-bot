-- V0002: Добавление идентификаторов ордеров в trades
-- Для отслеживания связи между сделками и ордерами

ALTER TABLE trades ADD COLUMN broker_order_id TEXT;
ALTER TABLE trades ADD COLUMN client_order_id TEXT;
ALTER TABLE trades ADD COLUMN filled REAL DEFAULT 0;