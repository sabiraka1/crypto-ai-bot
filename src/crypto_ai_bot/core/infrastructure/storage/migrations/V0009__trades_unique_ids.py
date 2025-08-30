-- Индексы для дедупликации сделок
CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_client_order_id
  ON trades (client_order_id)
  WHERE client_order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_broker_order_id
  ON trades (broker_order_id)
  WHERE broker_order_id IS NOT NULL;
