-- Индексы для ускорения запросов
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts_ms);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts_ms);
CREATE INDEX IF NOT EXISTS idx_audit_topic_ts ON audit(topic, ts_ms);

CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
