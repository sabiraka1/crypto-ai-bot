# src/crypto_ai_bot/core/settings.py
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional


def _to_bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    s = str(x).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


class Settings:
    """
    Единый конфиг с поддержкой UPPER_CASE и snake_case алиасов.
    build() — из os.environ; from_reader() — из dict-like (например, dotenv values).
    """

    # ---- дефолты (канонические имена) ----
    MODE: str = "paper"                       # paper | live | backtest
    EXCHANGE: str = "gateio"

    API_KEY: Optional[str] = None
    API_SECRET: Optional[str] = None
    CLIENT_ORDER_ID_PREFIX: str = "cai"       # префикс для Gate.io params["text"]

    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "15m"

    POSITION_SIZE_USD: float = 10.0           # размер позиций в валюте котировки
    FEE_TAKER_BPS: float = 10.0               # комиссия такер, bps
    SLIPPAGE_BPS: float = 20.0                # бюджет слиппеджа, bps
    STOP_LOSS_PCT: float = 0.02               # доля, 0.02 = 2%
    TAKE_PROFIT_PCT: float = 0.03             # доля, 0.03 = 3%

    IDEMPOTENCY_BUCKET_MS: int = 5_000
    IDEMPOTENCY_TTL_SEC: int = 300

    RL_EVALUATE_PER_MIN: int = 60
    RL_ORDERS_PER_MIN: int = 10

    MAX_TIME_DRIFT_MS: int = 2_500
    TIME_DRIFT_URLS: str = "https://worldtimeapi.org/api/timezone/Etc/UTC,https://worldtimeapi.org/api/ip"

    # Оркестратор / периодические тики
    EVAL_INTERVAL_SEC: float = 60.0
    EXITS_INTERVAL_SEC: float = 5.0
    RECONCILE_INTERVAL_SEC: float = 60.0
    BALANCE_CHECK_INTERVAL_SEC: float = 300.0
    BALANCE_TOLERANCE: float = 1e-4
    BUS_DLQ_RETRY_SEC: float = 10.0

    # Circuit breaker (для брокера)
    CB_FAIL_THRESHOLD: int = 5
    CB_OPEN_TIMEOUT_SEC: float = 30.0
    CB_HALF_OPEN_CALLS: int = 1
    CB_WINDOW_SEC: float = 60.0

    # Логи/прочее
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    DB_PATH: str = "./data/trades.db"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    TZ: str = "Europe/Istanbul"

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_SECRET: Optional[str] = None

    # здесь в рантайме можно положить limiter/risk_manager и пр.
    limiter: Any = None
    risk_manager: Any = None

    # ---- алиасы (поддержка старых/альтернативных имён) ----
    _ALIASES: Dict[str, str] = {
        # размеры позиции/комиссии
        "position_size": "POSITION_SIZE_USD",
        "position_size_usd": "POSITION_SIZE_USD",
        "fee_bps": "FEE_TAKER_BPS",

        # telegram
        "telegram_webhook_secret": "TELEGRAM_BOT_SECRET",

        # таймдрейф
        "time_drift_limit_ms": "MAX_TIME_DRIFT_MS",

        # для обратной совместимости snake_case → UPPER_CASE
        "mode": "MODE",
        "exchange": "EXCHANGE",
        "api_key": "API_KEY",
        "api_secret": "API_SECRET",
        "client_order_id_prefix": "CLIENT_ORDER_ID_PREFIX",
        "symbol": "SYMBOL",
        "timeframe": "TIMEFRAME",
        "fee_taker_bps": "FEE_TAKER_BPS",
        "slippage_bps": "SLIPPAGE_BPS",
        "stop_loss_pct": "STOP_LOSS_PCT",
        "take_profit_pct": "TAKE_PROFIT_PCT",
        "idempotency_bucket_ms": "IDEMPOTENCY_BUCKET_MS",
        "idempotency_ttl_sec": "IDEMPOTENCY_TTL_SEC",
        "rl_evaluate_per_min": "RL_EVALUATE_PER_MIN",
        "rl_orders_per_min": "RL_ORDERS_PER_MIN",
        "max_time_drift_ms": "MAX_TIME_DRIFT_MS",
        "time_drift_urls": "TIME_DRIFT_URLS",
        "eval_interval_sec": "EVAL_INTERVAL_SEC",
        "exits_interval_sec": "EXITS_INTERVAL_SEC",
        "reconcile_interval_sec": "RECONCILE_INTERVAL_SEC",
        "balance_check_interval_sec": "BALANCE_CHECK_INTERVAL_SEC",
        "balance_tolerance": "BALANCE_TOLERANCE",
        "bus_dlq_retry_sec": "BUS_DLQ_RETRY_SEC",
        "cb_fail_threshold": "CB_FAIL_THRESHOLD",
        "cb_open_timeout_sec": "CB_OPEN_TIMEOUT_SEC",
        "cb_half_open_calls": "CB_HALF_OPEN_CALLS",
        "cb_window_sec": "CB_WINDOW_SEC",
        "log_level": "LOG_LEVEL",
        "log_json": "LOG_JSON",
        "db_path": "DB_PATH",
        "public_base_url": "PUBLIC_BASE_URL",
        "tz": "TZ",
        "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
        "telegram_bot_secret": "TELEGRAM_BOT_SECRET",
    }

    # ---- конструкторы ----

    @classmethod
    def build(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        e = dict(os.environ if env is None else env)

        def get(key: str, default: Any = None) -> Any:
            if key in e:
                return e[key]
            # поддержка алиасов (и в upper, и в lower регистрах)
            for cand in (key.lower(), key.upper()):
                if cand in cls._ALIASES:
                    alias = cls._ALIASES[cand]
                    if alias in e:
                        return e[alias]
            return default

        s = cls()

        # базовые
        s.MODE = str(get("MODE", s.MODE))
        s.EXCHANGE = str(get("EXCHANGE", s.EXCHANGE))

        s.API_KEY = get("API_KEY", s.API_KEY)
        s.API_SECRET = get("API_SECRET", s.API_SECRET)
        s.CLIENT_ORDER_ID_PREFIX = str(get("CLIENT_ORDER_ID_PREFIX", s.CLIENT_ORDER_ID_PREFIX))

        s.SYMBOL = str(get("SYMBOL", s.SYMBOL))
        s.TIMEFRAME = str(get("TIMEFRAME", s.TIMEFRAME))

        # торговые параметры
        s.POSITION_SIZE_USD = _to_float(get("POSITION_SIZE_USD", get("POSITION_SIZE", s.POSITION_SIZE_USD)), s.POSITION_SIZE_USD)
        s.FEE_TAKER_BPS = _to_float(get("FEE_TAKER_BPS", get("FEE_BPS", s.FEE_TAKER_BPS)), s.FEE_TAKER_BPS)
        s.SLIPPAGE_BPS = _to_float(get("SLIPPAGE_BPS", s.SLIPPAGE_BPS), s.SLIPPAGE_BPS)
        s.STOP_LOSS_PCT = _to_float(get("STOP_LOSS_PCT", s.STOP_LOSS_PCT), s.STOP_LOSS_PCT)
        s.TAKE_PROFIT_PCT = _to_float(get("TAKE_PROFIT_PCT", s.TAKE_PROFIT_PCT), s.TAKE_PROFIT_PCT)

        # идемпотентность / rate limit
        s.IDEMPOTENCY_BUCKET_MS = _to_int(get("IDEMPOTENCY_BUCKET_MS", s.IDEMPOTENCY_BUCKET_MS), s.IDEMPOTENCY_BUCKET_MS)
        s.IDEMPOTENCY_TTL_SEC = _to_int(get("IDEMPOTENCY_TTL_SEC", s.IDEMPOTENCY_TTL_SEC), s.IDEMPOTENCY_TTL_SEC)
        s.RL_EVALUATE_PER_MIN = _to_int(get("RL_EVALUATE_PER_MIN", s.RL_EVALUATE_PER_MIN), s.RL_EVALUATE_PER_MIN)
        s.RL_ORDERS_PER_MIN = _to_int(get("RL_ORDERS_PER_MIN", s.RL_ORDERS_PER_MIN), s.RL_ORDERS_PER_MIN)

        # дрейф времени
        s.MAX_TIME_DRIFT_MS = _to_int(get("MAX_TIME_DRIFT_MS", get("TIME_DRIFT_LIMIT_MS", s.MAX_TIME_DRIFT_MS)), s.MAX_TIME_DRIFT_MS)
        s.TIME_DRIFT_URLS = str(get("TIME_DRIFT_URLS", s.TIME_DRIFT_URLS))

        # интервалы тиков
        s.EVAL_INTERVAL_SEC = _to_float(get("EVAL_INTERVAL_SEC", s.EVAL_INTERVAL_SEC), s.EVAL_INTERVAL_SEC)
        s.EXITS_INTERVAL_SEC = _to_float(get("EXITS_INTERVAL_SEC", s.EXITS_INTERVAL_SEC), s.EXITS_INTERVAL_SEC)
        s.RECONCILE_INTERVAL_SEC = _to_float(get("RECONCILE_INTERVAL_SEC", s.RECONCILE_INTERVAL_SEC), s.RECONCILE_INTERVAL_SEC)
        s.BALANCE_CHECK_INTERVAL_SEC = _to_float(get("BALANCE_CHECK_INTERVAL_SEC", s.BALANCE_CHECK_INTERVAL_SEC), s.BALANCE_CHECK_INTERVAL_SEC)
        s.BALANCE_TOLERANCE = _to_float(get("BALANCE_TOLERANCE", s.BALANCE_TOLERANCE), s.BALANCE_TOLERANCE)
        s.BUS_DLQ_RETRY_SEC = _to_float(get("BUS_DLQ_RETRY_SEC", s.BUS_DLQ_RETRY_SEC), s.BUS_DLQ_RETRY_SEC)

        # circuit breaker
        s.CB_FAIL_THRESHOLD = _to_int(get("CB_FAIL_THRESHOLD", s.CB_FAIL_THRESHOLD), s.CB_FAIL_THRESHOLD)
        s.CB_OPEN_TIMEOUT_SEC = _to_float(get("CB_OPEN_TIMEOUT_SEC", s.CB_OPEN_TIMEOUT_SEC), s.CB_OPEN_TIMEOUT_SEC)
        s.CB_HALF_OPEN_CALLS = _to_int(get("CB_HALF_OPEN_CALLS", s.CB_HALF_OPEN_CALLS), s.CB_HALF_OPEN_CALLS)
        s.CB_WINDOW_SEC = _to_float(get("CB_WINDOW_SEC", s.CB_WINDOW_SEC), s.CB_WINDOW_SEC)

        # телеграм/логи
        s.TELEGRAM_BOT_TOKEN = get("TELEGRAM_BOT_TOKEN", s.TELEGRAM_BOT_TOKEN)
        s.TELEGRAM_BOT_SECRET = get("TELEGRAM_BOT_SECRET", get("TELEGRAM_WEBHOOK_SECRET", s.TELEGRAM_BOT_SECRET))
        s.LOG_LEVEL = str(get("LOG_LEVEL", s.LOG_LEVEL))
        s.LOG_JSON = _to_bool(get("LOG_JSON", s.LOG_JSON), s.LOG_JSON)
        s.DB_PATH = str(get("DB_PATH", s.DB_PATH))
        s.PUBLIC_BASE_URL = str(get("PUBLIC_BASE_URL", s.PUBLIC_BASE_URL))
        s.TZ = str(get("TZ", s.TZ))

        return s

    @classmethod
    def from_reader(cls, reader: Mapping[str, Any]) -> "Settings":
        # совместимость: можно прокинуть словарь из dotenv
        return cls.build(reader)

    # ---- алиасы для getattr ----
    @classmethod
    def _canon_key(cls, name: str) -> str:
        k = name
        if k in cls.__dict__:
            return k
        if k in cls._ALIASES:
            return cls._ALIASES[k]
        if k.upper() in cls._ALIASES.values():
            return k.upper()
        return k

    def __getattr__(self, name: str) -> Any:
        # поддерживаем snake_case алиасы
        if name in self._ALIASES:
            return getattr(self, self._ALIASES[name], None)
        raise AttributeError(name)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
