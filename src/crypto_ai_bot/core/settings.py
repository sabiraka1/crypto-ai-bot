from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import List


@dataclass
class Settings:
    MODE: str
    EXCHANGE: str
    API_KEY: str
    API_SECRET: str
    SANDBOX: bool

    SYMBOL: str
    FIXED_AMOUNT: Decimal

    IDEMPOTENCY_BUCKET_MS: int
    IDEMPOTENCY_TTL_SEC: int

    ORDER_AUTO_CANCEL_TTL_SEC: int

    RISK_FEE_PCT_EST: Decimal
    RISK_SLIPPAGE_PCT_EST: Decimal

    # --- backup ---
    DB_PATH: str
    DB_BACKUP_DIR: str
    DB_BACKUP_RETENTION_DAYS: int
    DB_BACKUP_COMPRESS: bool

    @staticmethod
    def load() -> "Settings":
        def _d(name: str, default: str) -> str:
            return os.getenv(name, default)

        def _b(name: str, default: bool) -> bool:
            return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}

        def _i(name: str, default: int) -> int:
            return int(os.getenv(name, str(default)))

        def _dec(name: str, default: str) -> Decimal:
            return Decimal(os.getenv(name, default))

        return Settings(
            MODE=_d("MODE", "paper"),
            EXCHANGE=_d("EXCHANGE", "gateio"),
            API_KEY=_d("API_KEY", ""),
            API_SECRET=_d("API_SECRET", ""),
            SANDBOX=_b("SANDBOX", True),

            SYMBOL=_d("SYMBOL", "BTC/USDT"),
            FIXED_AMOUNT=_dec("FIXED_AMOUNT", "10"),

            IDEMPOTENCY_BUCKET_MS=_i("IDEMPOTENCY_BUCKET_MS", 5_000),
            IDEMPOTENCY_TTL_SEC=_i("IDEMPOTENCY_TTL_SEC", 600),

            ORDER_AUTO_CANCEL_TTL_SEC=_i("ORDER_AUTO_CANCEL_TTL_SEC", 120),

            RISK_FEE_PCT_EST=_dec("RISK_FEE_PCT_EST", "0.001"),
            RISK_SLIPPAGE_PCT_EST=_dec("RISK_SLIPPAGE_PCT_EST", "0.0005"),

            DB_PATH=_d("DB_PATH", "./data/bot.sqlite3"),
            DB_BACKUP_DIR=_d("DB_BACKUP_DIR", "./data/backups"),
            DB_BACKUP_RETENTION_DAYS=_i("DB_BACKUP_RETENTION_DAYS", 7),
            DB_BACKUP_COMPRESS=_b("DB_BACKUP_COMPRESS", False),
        )

    # Опционально: поддержка multi-symbol, если уже внедрено в compose
    def get_symbols(self) -> List[str]:
        raw = os.getenv("SYMBOLS")
        if not raw:
            return [self.SYMBOL]
        return [s.strip() for s in raw.split(",") if s.strip()]