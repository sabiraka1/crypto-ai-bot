ALTER TABLE positions ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_positions_version ON positions(symbol, version);
