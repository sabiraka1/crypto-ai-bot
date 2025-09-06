-- V0011: Расширение позиций для полного отслеживания PnL

-- Добавляем новые поля если их еще нет
ALTER TABLE positions ADD COLUMN avg_entry_price REAL NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN unrealized_pnl REAL NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN updated_ts_ms INTEGER NOT NULL DEFAULT 0;

-- Мигрируем существующие данные
UPDATE positions 
SET avg_entry_price = COALESCE(avg_entry_price, average_price, 0)
WHERE avg_entry_price = 0;

UPDATE positions 
SET updated_ts_ms = COALESCE(updated_ts_ms, 0)
WHERE updated_ts_ms = 0;