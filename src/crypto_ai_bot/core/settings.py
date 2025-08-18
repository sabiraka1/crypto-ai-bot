# src/crypto_ai_bot/core/settings.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Mapping
from .config.env_reader import EnvReader

@dataclass(slots=True)
class Settings:
    # Core
    mode: str
    enable_trading: bool

    # Exchange / broker
    exchange: str
    api_key: Optional[str]
    api_secret: Optional[str]
    client_order_id_prefix: str

    # Instrument / timeframe
    symbol: str
    timeframe: str
    position_size: float

    # History / lookback
    limit_bars: int
    lookback_limit: int

    # Fees / slippage (bps)
    fee_bps: float
    slippage_bps: float

    # Storage
    db_path: str

    # CCXT local rate-limit
    ccxt_local_rl_calls: int
    ccxt_local_rl_window: float

    # Observability / HTTP
    public_base_url: Optional[str]
    log_level: str
    log_json: bool
    context_http_timeout_sec: float

    # Time sync in /health
    max_time_drift_ms: int
    time_drift_urls: List[str]

    # Telegram
    telegram_bot_token: Optional[str]
    telegram_webhook_secret: Optional[str]

    # Orchestrator
    tick_period_sec: float
    perf_budget_flow_p99_ms: int
    perf_budget_decision_p99_ms: int
    perf_budget_order_p99_ms: int

    # Misc
    tz: str

    # ---------- Builders ----------
    @classmethod
    def build(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        reader = EnvReader(env)
        return cls.from_reader(reader)

    @classmethod
    def from_reader(cls, env: EnvReader) -> "Settings":
        return cls(
            # Core
            mode=(env.get("MODE","paper") or "paper").lower(),
            enable_trading=env.get_bool("ENABLE_TRADING", False),
            # Exchange
            exchange=(env.get("EXCHANGE","gateio") or "gateio").lower(),
            api_key=env.get("API_KEY"),
            api_secret=env.get("API_SECRET"),
            client_order_id_prefix=env.get("CLIENT_ORDER_ID_PREFIX","cai") or "cai",
            # Instrument
            symbol=env.get("SYMBOL","BTC/USDT") or "BTC/USDT",
            timeframe=env.get("TIMEFRAME","15m") or "15m",
            position_size=float(env.get_float("POSITION_SIZE", 10)),
            # History
            limit_bars=env.get_int("LIMIT_BARS", 300),
            lookback_limit=env.get_int("LOOKBACK_LIMIT", 300),
            # Fees / slippage
            fee_bps=float(env.get_float("FEE_BPS", 10.0)),
            slippage_bps=float(env.get_float("SLIPPAGE_BPS", 5.0)),
            # Storage
            db_path=env.get("DB_PATH","./crypto.db") or "./crypto.db",
            # CCXT RL
            ccxt_local_rl_calls=env.get_int("CCXT_LOCAL_RL_CALLS", 8),
            ccxt_local_rl_window=float(env.get_float("CCXT_LOCAL_RL_WINDOW", 1.0)),
            # Observability / HTTP
            public_base_url=env.get("PUBLIC_BASE_URL"),
            log_level=(env.get("LOG_LEVEL","INFO") or "INFO").upper(),
            log_json=env.get_bool("LOG_JSON", False),
            context_http_timeout_sec=float(env.get_float("CONTEXT_HTTP_TIMEOUT_SEC", 2.0)),
            # Time sync
            max_time_drift_ms=env.get_int("MAX_TIME_DRIFT_MS", 2500),
            time_drift_urls=env.get_list("TIME_DRIFT_URLS", ["https://worldtimeapi.org/api/timezone/Etc/UTC","https://worldtimeapi.org/api/ip"]),
            # Telegram
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=env.get("TELEGRAM_WEBHOOK_SECRET"),
            # Orchestrator
            tick_period_sec=float(env.get_float("TICK_PERIOD_SEC", 60.0)),
            perf_budget_flow_p99_ms=env.get_int("PERF_BUDGET_FLOW_P99_MS", 0),
            perf_budget_decision_p99_ms=env.get_int("PERF_BUDGET_DECISION_P99_MS", 0),
            perf_budget_order_p99_ms=env.get_int("PERF_BUDGET_ORDER_P99_MS", 0),
            # Misc
            tz=env.get("TZ","Europe/Istanbul") or "Europe/Istanbul",
        )
