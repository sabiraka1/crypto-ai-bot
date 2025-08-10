import os
from dataclasses import dataclass
from typing import List

# ==== Helpers ====
def getenv_bool(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(default))).lower() in ("1", "true", "yes", "on")

def getenv_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default

def getenv_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default

def getenv_list(name: str, default: List[str] = None, sep: str = ",") -> List[str]:
    val = os.getenv(name)
    if val:
        return [x.strip() for x in val.split(sep) if x.strip()]
    return default or []

# ==== Telegram ====
@dataclass
class TelegramSettings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    chat_id: str = os.getenv("CHAT_ID", "")
    admin_chat_ids: List[str] = getenv_list("ADMIN_CHAT_IDS", [])
    secret_token: str = os.getenv("TELEGRAM_SECRET_TOKEN", "")

telegram = TelegramSettings()

# ==== Gate.io API ====
@dataclass
class GateAPISettings:
    api_key: str = os.getenv("GATE_API_KEY", "")
    api_secret: str = os.getenv("GATE_API_SECRET", "")

gate_api = GateAPISettings()

# ==== Bot Settings ====
@dataclass
class BotSettings:
    port: int = getenv_int("PORT", 5000)
    python_unbuffered: bool = getenv_bool("PYTHONUNBUFFERED", True)
    timezone: str = os.getenv("TZ", "UTC")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    safe_mode: bool = getenv_bool("SAFE_MODE", True)
    enable_webhook: bool = getenv_bool("ENABLE_WEBHOOK", True)
    enable_trading: bool = getenv_bool("ENABLE_TRADING", True)
    command_cooldown: int = getenv_int("COMMAND_COOLDOWN", 3)

bot_settings = BotSettings()

# ==== Trading Parameters ====
@dataclass
class TradingParameters:
    symbol: str = os.getenv("SYMBOL", "BTC/USDT")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
    analysis_interval: int = getenv_int("ANALYSIS_INTERVAL", 15)
    trade_amount: float = getenv_float("TRADE_AMOUNT", 3.0)
    test_trade_amount: float = getenv_float("TEST_TRADE_AMOUNT", 3.0)
    min_score_to_buy: float = getenv_float("MIN_SCORE_TO_BUY", 0.65)
    ai_min_to_trade: float = getenv_float("AI_MIN_TO_TRADE", 0.70)
    ai_enable: bool = getenv_bool("AI_ENABLE", True)
    ai_failover_score: float = getenv_float("AI_FAILOVER_SCORE", 0.55)
    enforce_ai_gate: bool = getenv_bool("ENFORCE_AI_GATE", True)

trading_params = TradingParameters()

# ==== Risk Management ====
@dataclass
class RiskManagement:
    stop_loss_pct: float = getenv_float("STOP_LOSS_PCT", 2.0)
    take_profit_pct: float = getenv_float("TAKE_PROFIT_PCT", 1.5)
    position_min_fraction: float = getenv_float("POSITION_MIN_FRACTION", 0.30)
    position_max_fraction: float = getenv_float("POSITION_MAX_FRACTION", 1.00)
    bull_market_modifier: float = getenv_float("BULL_MARKET_MODIFIER", -0.20)
    bear_market_modifier: float = getenv_float("BEAR_MARKET_MODIFIER", 0.40)
    overheated_modifier: float = getenv_float("OVERHEATED_MODIFIER", 0.30)
    post_sale_cooldown: int = getenv_int("POST_SALE_COOLDOWN", 60)
    volatility_threshold: float = getenv_float("VOLATILITY_THRESHOLD", 5.0)
    market_reevaluation: int = getenv_int("MARKET_REEVALUATION", 4)
    rsi_overbought: int = getenv_int("RSI_OVERBOUGHT", 70)
    rsi_critical: int = getenv_int("RSI_CRITICAL", 90)
    rsi_close_candles: int = getenv_int("RSI_CLOSE_CANDLES", 5)

risk_manager = RiskManagement()

# ==== Profit Manager (New) ====
@dataclass
class ProfitManager:
    tp1_pct: float = getenv_float("TP1_PCT", 0.5)
    tp2_pct: float = getenv_float("TP2_PCT", 1.0)
    tp3_pct: float = getenv_float("TP3_PCT", 1.5)
    tp4_pct: float = getenv_float("TP4_PCT", 2.0)
    tp1_size: float = getenv_float("TP1_SIZE", 0.25)
    tp2_size: float = getenv_float("TP2_SIZE", 0.25)
    tp3_size: float = getenv_float("TP3_SIZE", 0.25)
    tp4_size: float = getenv_float("TP4_SIZE", 0.25)
    trailing_stop_enable: bool = getenv_bool("TRAILING_STOP_ENABLE", True)
    trailing_stop_pct: float = getenv_float("TRAILING_STOP_PCT", 0.5)

profit_manager = ProfitManager()

# ==== Performance Tracker (New) ====
@dataclass
class PerformanceTracker:
    max_consecutive_losses: int = getenv_int("MAX_CONSECUTIVE_LOSSES", 5)
    max_drawdown_pct: float = getenv_float("MAX_DRAWDOWN_PCT", 15.0)
    min_win_rate: float = getenv_float("MIN_WIN_RATE", 35.0)
    negative_sharpe_limit: float = getenv_float("NEGATIVE_SHARPE_LIMIT", 0.0)
    poor_rr_threshold: float = getenv_float("POOR_RR_THRESHOLD", 0.5)
    alert_interval_sec: int = getenv_int("PERFORMANCE_ALERT_INTERVAL", 300)

performance_tracker = PerformanceTracker()

# ==== Files & Paths ====
@dataclass
class Paths:
    model_dir: str = os.getenv("MODEL_DIR", "models")
    closed_trades_csv: str = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
    signals_csv: str = os.getenv("SIGNALS_CSV", "signals_snapshots.csv")
    logs_dir: str = os.getenv("LOGS_DIR", "logs")

paths = Paths()

# ==== Webhook ====
@dataclass
class Webhook:
    public_url: str = os.getenv("PUBLIC_URL", "")
    secret: str = os.getenv("WEBHOOK_SECRET", "")

webhook = Webhook()
