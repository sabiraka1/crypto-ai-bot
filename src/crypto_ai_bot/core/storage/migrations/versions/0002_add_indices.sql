CREATE INDEX IF NOT EXISTS ix_trades_symbol_ts ON trades(symbol, ts DESC);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS ix_snapshots_symbol_ts ON snapshots(symbol, ts DESC);
