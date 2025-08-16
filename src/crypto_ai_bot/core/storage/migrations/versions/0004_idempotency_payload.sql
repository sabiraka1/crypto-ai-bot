-- src/crypto_ai_bot/core/storage/migrations/versions/0004_idempotency_payload.sql
ALTER TABLE idempotency ADD COLUMN payload_json TEXT;
