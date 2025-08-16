CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    state       TEXT NOT NULL CHECK (state IN ('claimed','committed')),
    expires_at  INTEGER NOT NULL,         -- timestamp ms
    updated_at  INTEGER NOT NULL          -- timestamp ms
);

CREATE INDEX IF NOT EXISTS ix_idemp_expires ON idempotency(expires_at);
