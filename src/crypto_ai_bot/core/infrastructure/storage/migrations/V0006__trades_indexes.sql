-- V0006__trades_indexes.sql
-- Назначение: ускорить выборки по сделкам и усилить идемпотентность ордеров.

-- Индекс по символу и времени (частые выборки за сегодня/интервальные отчёты)
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
    ON trades(symbol, ts_ms);

-- Уникальный индекс по client_order_id (биржевой идемпотентный идентификатор)
-- В SQLite NULL значения не конфликтуют между собой, поэтому добавляем условие:
CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_client_order_id
    ON trades(client_order_id)
    WHERE client_order_id IS NOT NULL;

-- (Необязательно) Индекс по ts_ms для диапазонных запросов
CREATE INDEX IF NOT EXISTS idx_trades_ts
    ON trades(ts_ms);
