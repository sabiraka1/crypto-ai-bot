-- 0005_audit_table.sql
-- Журнал аудита решений и событий

CREATE TABLE IF NOT EXISTS audit_log(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,            -- UTC epoch milliseconds
    event_type   TEXT    NOT NULL,            -- e.g. 'decision', 'order_submitted', 'order_filled'
    trace_id     TEXT,
    payload_json TEXT    NOT NULL             -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_audit_ts            ON audit_log(ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_audit_type_ts       ON audit_log(event_type, ts_ms DESC);
