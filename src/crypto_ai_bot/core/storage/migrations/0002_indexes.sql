-- 0002_indexes.sql
-- безопасные индексы на таблицы из 0001_init
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms);
CREATE INDEX IF NOT EXISTS idx_audit_ts        ON audit_log(ts_ms);