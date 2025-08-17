# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

# ENV читаем ТОЛЬКО здесь.
import os, json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict


def _to_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    v = v.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _to_int(v: str | None, default: int) -> int:
    try:
        return int(str(v)) if v is not None else default
    except Exception:
        return default


def _to_float(v: str | None, default: float) -> float:
    try:
        return float(str(v)) if v is not None else default
    except Exception:
        return default


def _to_decimal(v: str | None, default: str) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else Decimal(default)
    except Exception:
        return Decimal(default)


def _parse_mapping(value: str | None, default: Dict[str, Any]) -> Dict[str, Any]:
    """
    Пытаемся разобрать две формы:
      1) JSON: {"OrderSubmittedEvent":"drop_oldest","ErrorEvent":"keep_latest"}
      2) k=v;k=v (строки): OrderSubmittedEvent=drop_oldest;ErrorEvent=keep_latest
         (для размеров: OrderSubmittedEvent=2000;ErrorEvent=500)
    """
    if value is None or not str(value).strip():
        return dict(default)
    s = str(value).strip()
    # JSON сначала
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # k=v;k=v
    out: Dict[str, Any] = {}
    try:
        parts = [p for p in s.split(";") if p]
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                k, v = k.strip(), v.strip()
                # попробуем числовое
                if v.isdigit():
                    out[k] = int(v)
                else:
                    try:
                        out[k] = float(v) if "." in v else v
                    except Exception:
                        out[k] = v
        if out:
            return out
    except Exception:
        pass
    return dict(default)


@dataclass
class Settings:
    # --- режим/общие ---
    MODE: str = field(default_factory=lambda: os.getenv("MODE", "paper"))
    SYMBOL: str = field(default_factory=lambda: os.getenv("SYMBOL", "BTC/USDT"))
    TIMEFRAME: str = field(default_factory=lambda: os.getenv("TIMEFRAME", "1h"))
    ENABLE_TRADING: bool = field(default_factory=lambda: _to_bool(os.getenv("ENABLE_TRADING"), False))
    DEFAULT_ORDER_SIZE: str = field(default_factory=lambda: os.getenv("DEFAULT_ORDER_SIZE", "0.01"))
    DB_PATH: str = field(default_factory=lambda: os.getenv("DB_PATH", "data/bot.sqlite"))

    # --- риски/пороги ---
    IDEMPOTENCY_TTL_SECONDS: int = field(default_factory=lambda: _to_int(os.getenv("IDEMPOTENCY_TTL_SECONDS"), 300))

    # --- Risk / exposure / history ---
    MIN_HISTORY_BARS: int = field(default_factory=lambda: _to_int(os.getenv("MIN_HISTORY_BARS"), 300))
    MAX_EXPOSURE_UNITS: str = field(default_factory=lambda: os.getenv("MAX_EXPOSURE_UNITS", "0"))


    # --- time sync / health ---
    TIME_DRIFT_LIMIT_MS: int = field(default_factory=lambda: _to_int(os.getenv("TIME_DRIFT_LIMIT_MS"), 1000))
    # Через запятую. Можно оставить пустым — дефолты возьмём в utils/time_sync.py
    TIME_DRIFT_URLS: list[str] = field(
        default_factory=lambda: [u.strip() for u in os.getenv("TIME_DRIFT_URLS", "").split(",") if u.strip()]
    )
    HEALTH_TIME_TIMEOUT_S: float = field(default_factory=lambda: _to_float(os.getenv("HEALTH_TIME_TIMEOUT_S"), 2.0))

    # --- scoring/thresholds (веса) ---
    SCORE_RULE_WEIGHT: float = field(default_factory=lambda: _to_float(os.getenv("SCORE_RULE_WEIGHT"), 0.5))
    SCORE_AI_WEIGHT: float = field(default_factory=lambda: _to_float(os.getenv("SCORE_AI_WEIGHT"), 0.5))
    THRESHOLD_BUY: float = field(default_factory=lambda: _to_float(os.getenv("THRESHOLD_BUY"), 0.55))
    THRESHOLD_SELL: float = field(default_factory=lambda: _to_float(os.getenv("THRESHOLD_SELL"), 0.45))

    # --- Event Bus настройки (если используется async_bus) ---
    BUS_STRATEGIES: Dict[str, str] = field(
        default_factory=lambda: _parse_mapping(
            os.getenv("BUS_STRATEGIES"),
            {"OrderSubmittedEvent": "drop_oldest", "ErrorEvent": "keep_latest"},
        )
    )
    BUS_QUEUE_SIZES: Dict[str, int] = field(
        default_factory=lambda: _parse_mapping(
            os.getenv("BUS_QUEUE_SIZES"),
            {"OrderSubmittedEvent": 2000, "ErrorEvent": 500},
        )
    )
    BUS_DLQ_MAX: int = field(default_factory=lambda: _to_int(os.getenv("BUS_DLQ_MAX"), 500))

    # --- Telegram / Secrets (опционально, без падений) ---
    TELEGRAM_BOT_TOKEN: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN"))
    TELEGRAM_SECRET_TOKEN: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_SECRET_TOKEN"))

    @classmethod
    def build(cls) -> "Settings":
        s = cls()
        # SAFE_MODE → форсируем выключение торговли
        if _to_bool(os.getenv("SAFE_MODE"), False):
            s.ENABLE_TRADING = False

        # Валидация весов (мягкая)
        total_w = float(s.SCORE_RULE_WEIGHT) + float(s.SCORE_AI_WEIGHT)
        if total_w <= 0:
            s.SCORE_RULE_WEIGHT, s.SCORE_AI_WEIGHT = 0.5, 0.5

        # Валидация числа в DEFAULT_ORDER_SIZE (мягко)
        try:
            Decimal(s.DEFAULT_ORDER_SIZE)
        except Exception:
            s.DEFAULT_ORDER_SIZE = "0.01"

        return s
