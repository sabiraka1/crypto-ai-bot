# V007_perf_indexes.py
def up(conn):
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts_ms);")
    conn.commit()
