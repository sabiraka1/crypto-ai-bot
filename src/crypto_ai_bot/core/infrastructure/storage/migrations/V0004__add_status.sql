-- V0004: Добавление статусов для отслеживания состояний

ALTER TABLE trades ADD COLUMN status TEXT DEFAULT 'completed';
ALTER TABLE positions ADD COLUMN status TEXT DEFAULT 'open';

-- Индексы для быстрого поиска по статусу
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);