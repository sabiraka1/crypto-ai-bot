import os
from dataclasses import dataclass, field
from typing import List
from enum import Enum

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

# ==== Market Conditions ====
class MarketCondition(Enum):
    STRONG_BULL = "strong_bull"
    WEAK_BULL = "weak_bull"
    SIDEWAYS = "sideways"
    WEAK_BEAR = "weak_bear"
    STRONG_BEAR = "strong_bear"

class TradingState(Enum):
    WAITING = "waiting"
    ANALYZING = "analyzing"
    ENTERING = "entering"
    IN_POSITION = "in_position"
    EXITING = "exiting"
    COOLDOWN = "cooldown"
    PAUSED = "paused"

# ==== Главная конфигурация ====
@dataclass
class TradingConfig:
    """✅ ОБНОВЛЕНО: Единая конфигурация с поддержкой UNIFIED ATR системы"""

    # ==== Telegram ====
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHAT_ID: str = os.getenv("CHAT_ID", "")
    ADMIN_CHAT_IDS: List[str] = field(default_factory=lambda: getenv_list("ADMIN_CHAT_IDS", []))
    TELEGRAM_SECRET_TOKEN: str = os.getenv("TELEGRAM_SECRET_TOKEN", "")

    # ==== Gate.io API ====
    GATE_API_KEY: str = os.getenv("GATE_API_KEY", "")
    GATE_API_SECRET: str = os.getenv("GATE_API_SECRET", "")

    # ==== Основные настройки бота ====
    PORT: int = getenv_int("PORT", 5000)
    SAFE_MODE: bool = getenv_bool("SAFE_MODE", True)
    ENABLE_WEBHOOK: bool = getenv_bool("ENABLE_WEBHOOK", True)
    ENABLE_TRADING: bool = getenv_bool("ENABLE_TRADING", True)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ==== Торговые параметры ====
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = getenv_int("ANALYSIS_INTERVAL", 15)
    POSITION_SIZE_USD: float = getenv_float("TRADE_AMOUNT", 3.0)

    # ==== ✅ НОВОЕ: UNIFIED ATR СИСТЕМА ====
    # Период для всех ATR расчетов в проекте
    ATR_PERIOD: int = getenv_int("ATR_PERIOD", 14)
    
    # Метод расчета ATR для risk manager (ewm/sma)
    RISK_ATR_METHOD: str = os.getenv("RISK_ATR_METHOD", "ewm").lower()
    
    # Включение сравнения old vs new ATR для отладки
    RISK_ATR_COMPARE: bool = getenv_bool("RISK_ATR_COMPARE", True)
    
    # Интервал информационных логов в секундах
    INFO_LOG_INTERVAL_SEC: int = getenv_int("INFO_LOG_INTERVAL_SEC", 300)
    
    # Волатильность и ATR пороги
    VOLATILITY_THRESHOLD: float = getenv_float("VOLATILITY_THRESHOLD", 5.0)
    
    # Периоды для различных расчетов (используют ATR_PERIOD если не заданы отдельно)
    VOLATILITY_LOOKBACK: int = getenv_int("VOLATILITY_LOOKBACK", 20)
    VOLUME_LOOKBACK: int = getenv_int("VOLUME_LOOKBACK", 20)

    # ==== Скоринг и AI ====
    MIN_SCORE_TO_BUY: float = getenv_float("MIN_SCORE_TO_BUY", 0.65)
    AI_MIN_TO_TRADE: float = getenv_float("AI_MIN_TO_TRADE", 0.70)
    AI_ENABLE: bool = getenv_bool("AI_ENABLE", True)
    AI_FAILOVER_SCORE: float = getenv_float("AI_FAILOVER_SCORE", 0.55)
    ENFORCE_AI_GATE: bool = getenv_bool("ENFORCE_AI_GATE", True)

    # ==== ✅ ОБНОВЛЕНО: Риск-менеджмент с ATR поддержкой ====
    STOP_LOSS_PCT: float = getenv_float("STOP_LOSS_PCT", 2.0)
    TAKE_PROFIT_PCT: float = getenv_float("TAKE_PROFIT_PCT", 1.5)
    POSITION_MIN_FRACTION: float = getenv_float("POSITION_MIN_FRACTION", 0.30)
    POSITION_MAX_FRACTION: float = getenv_float("POSITION_MAX_FRACTION", 1.00)
    POST_SALE_COOLDOWN: int = getenv_int("POST_SALE_COOLDOWN", 60)
    
    # Динамические модификаторы риска
    BULL_MARKET_MODIFIER: float = getenv_float("BULL_MARKET_MODIFIER", -0.20)
    BEAR_MARKET_MODIFIER: float = getenv_float("BEAR_MARKET_MODIFIER", 0.40)
    OVERHEATED_MODIFIER: float = getenv_float("OVERHEATED_MODIFIER", 0.30)
    
    # Пороги для риск-менеджмента
    MIN_STOP_PCT: float = getenv_float("MIN_STOP_PCT", 0.005)  # 0.5%
    MAX_STOP_PCT: float = getenv_float("MAX_STOP_PCT", 0.05)   # 5%

    # ==== Продвинутые Take Profit ====
    TP1_PCT: float = getenv_float("TP1_PCT", 0.5)
    TP2_PCT: float = getenv_float("TP2_PCT", 1.0)
    TP3_PCT: float = getenv_float("TP3_PCT", 1.5)
    TP4_PCT: float = getenv_float("TP4_PCT", 2.0)
    TP1_SIZE: float = getenv_float("TP1_SIZE", 0.25)
    TP2_SIZE: float = getenv_float("TP2_SIZE", 0.25)
    TP3_SIZE: float = getenv_float("TP3_SIZE", 0.25)
    TP4_SIZE: float = getenv_float("TP4_SIZE", 0.25)
    TRAILING_STOP_ENABLE: bool = getenv_bool("TRAILING_STOP_ENABLE", True)
    TRAILING_STOP_PCT: float = getenv_float("TRAILING_STOP_PCT", 0.5)

    # ==== Performance Tracking ====
    MAX_CONSECUTIVE_LOSSES: int = getenv_int("MAX_CONSECUTIVE_LOSSES", 5)
    MAX_DRAWDOWN_PCT: float = getenv_float("MAX_DRAWDOWN_PCT", 15.0)
    MIN_WIN_RATE: float = getenv_float("MIN_WIN_RATE", 35.0)
    NEGATIVE_SHARPE_LIMIT: float = getenv_float("NEGATIVE_SHARPE_LIMIT", 0.0)
    POOR_RR_THRESHOLD: float = getenv_float("POOR_RR_THRESHOLD", 0.5)
    PERFORMANCE_ALERT_INTERVAL: int = getenv_int("PERFORMANCE_ALERT_INTERVAL", 300)

    # ==== RSI настройки ====
    RSI_CLOSE_CANDLES: int = getenv_int("RSI_CLOSE_CANDLES", 5)
    RSI_CRITICAL: float = getenv_float("RSI_CRITICAL", 90.0)
    RSI_OVERBOUGHT: float = getenv_float("RSI_OVERBOUGHT", 70.0)

    # ==== Переоценка рынка ====
    MARKET_REEVALUATION: int = getenv_int("MARKET_REEVALUATION", 4)

    # ==== Файлы и пути ====
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    MODEL_DIR: str = os.getenv("MODEL_DIR", "models")
    CLOSED_TRADES_CSV: str = os.getenv("CLOSED_TRADES_CSV", os.path.join(DATA_DIR, "closed_trades.csv"))
    SIGNALS_CSV: str = os.getenv("SIGNALS_CSV", os.path.join(DATA_DIR, "signals_snapshots.csv"))
    LOGS_DIR: str = os.getenv("LOGS_DIR", "logs")

    # ==== Webhook ====
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # ==== Дополнительные настройки ====
    COMMAND_COOLDOWN: int = getenv_int("COMMAND_COOLDOWN", 3)

    def validate_config(self) -> List[str]:
        """✅ ОБНОВЛЕНО: Валидация конфигурации включая UNIFIED ATR параметры"""
        errors = []

        # Основные обязательные параметры
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN не задан")
        if not self.CHAT_ID:
            errors.append("CHAT_ID не задан")
        if not self.GATE_API_KEY:
            errors.append("GATE_API_KEY не задан")
        if not self.GATE_API_SECRET:
            errors.append("GATE_API_SECRET не задан")

        # Webhook валидация
        if self.ENABLE_WEBHOOK and not self.PUBLIC_URL:
            errors.append("ENABLE_WEBHOOK=1 но PUBLIC_URL не задан")
        if self.ENABLE_WEBHOOK and not self.WEBHOOK_SECRET:
            errors.append("ENABLE_WEBHOOK=1 но WEBHOOK_SECRET не задан")

        # Торговые параметры
        if self.POSITION_SIZE_USD <= 0:
            errors.append("POSITION_SIZE_USD должен быть > 0")
        if not (0.0 <= self.MIN_SCORE_TO_BUY <= 1.0):
            errors.append("MIN_SCORE_TO_BUY должен быть между 0.0 и 1.0")
        if not (0.0 <= self.AI_MIN_TO_TRADE <= 1.0):
            errors.append("AI_MIN_TO_TRADE должен быть между 0.0 и 1.0")

        # Риск-менеджмент валидация
        if self.STOP_LOSS_PCT <= 0:
            errors.append("STOP_LOSS_PCT должен быть > 0")
        if self.TAKE_PROFIT_PCT <= 0:
            errors.append("TAKE_PROFIT_PCT должен быть > 0")

        # ✅ НОВОЕ: Валидация UNIFIED ATR параметров
        if self.ATR_PERIOD <= 0:
            errors.append("ATR_PERIOD должен быть > 0")
        if self.ATR_PERIOD > 100:
            errors.append("ATR_PERIOD слишком большой (рекомендуется <= 100)")
            
        if self.RISK_ATR_METHOD not in ["ewm", "sma"]:
            errors.append(f"RISK_ATR_METHOD должен быть 'ewm' или 'sma', получен: {self.RISK_ATR_METHOD}")
            
        if self.INFO_LOG_INTERVAL_SEC <= 0:
            errors.append("INFO_LOG_INTERVAL_SEC должен быть > 0")
            
        if self.VOLATILITY_THRESHOLD <= 0:
            errors.append("VOLATILITY_THRESHOLD должен быть > 0")
        
        # Валидация границ риска
        if not (0.0 < self.MIN_STOP_PCT < self.MAX_STOP_PCT <= 1.0):
            errors.append(f"Некорректные границы стоп-лосса: MIN_STOP_PCT={self.MIN_STOP_PCT}, MAX_STOP_PCT={self.MAX_STOP_PCT}")

        # Валидация фракций позиции
        if not (0.0 <= self.POSITION_MIN_FRACTION <= self.POSITION_MAX_FRACTION <= 1.0):
            errors.append(f"Некорректные границы позиции: MIN={self.POSITION_MIN_FRACTION}, MAX={self.POSITION_MAX_FRACTION}")

        # Валидация Take Profit размеров
        total_tp_size = self.TP1_SIZE + self.TP2_SIZE + self.TP3_SIZE + self.TP4_SIZE
        if abs(total_tp_size - 1.0) > 0.01:  # Допускаем 1% погрешность
            errors.append(f"Сумма размеров TP должна быть ~1.0, получено: {total_tp_size:.3f}")

        return errors

    def get_webhook_url(self) -> str:
        """Получить URL webhook"""
        if not self.PUBLIC_URL or not self.WEBHOOK_SECRET:
            return ""
        return f"{self.PUBLIC_URL.rstrip('/')}/webhook/{self.WEBHOOK_SECRET}"

    def is_admin(self, chat_id: str) -> bool:
        """Проверить является ли пользователь админом"""
        return str(chat_id) in self.ADMIN_CHAT_IDS

    def get_tp_levels(self) -> List[dict]:
        """Получить уровни Take Profit"""
        return [
            {"level": 1, "pct": self.TP1_PCT, "size": self.TP1_SIZE},
            {"level": 2, "pct": self.TP2_PCT, "size": self.TP2_SIZE},
            {"level": 3, "pct": self.TP3_PCT, "size": self.TP3_SIZE},
            {"level": 4, "pct": self.TP4_PCT, "size": self.TP4_SIZE}
        ]

    # ✅ НОВЫЕ МЕТОДЫ ДЛЯ UNIFIED ATR СИСТЕМЫ

    def get_atr_config(self) -> dict:
        """Получить конфигурацию ATR для всех модулей"""
        return {
            "period": self.ATR_PERIOD,
            "risk_method": self.RISK_ATR_METHOD,
            "compare_enabled": self.RISK_ATR_COMPARE,
            "log_interval": self.INFO_LOG_INTERVAL_SEC,
            "volatility_threshold": self.VOLATILITY_THRESHOLD
        }

    def get_risk_config(self) -> dict:
        """Получить конфигурацию риск-менеджмента"""
        return {
            "atr_period": self.ATR_PERIOD,
            "atr_method": self.RISK_ATR_METHOD,
            "min_stop_pct": self.MIN_STOP_PCT,
            "max_stop_pct": self.MAX_STOP_PCT,
            "volatility_lookback": self.VOLATILITY_LOOKBACK,
            "volume_lookback": self.VOLUME_LOOKBACK,
            "market_modifiers": {
                "bull": self.BULL_MARKET_MODIFIER,
                "bear": self.BEAR_MARKET_MODIFIER,
                "overheated": self.OVERHEATED_MODIFIER
            }
        }

    def get_performance_thresholds(self) -> dict:
        """Получить пороги для performance tracking"""
        return {
            "max_consecutive_losses": self.MAX_CONSECUTIVE_LOSSES,
            "max_drawdown_pct": self.MAX_DRAWDOWN_PCT / 100.0,  # Конвертируем в доли
            "min_win_rate": self.MIN_WIN_RATE / 100.0,
            "negative_sharpe_limit": self.NEGATIVE_SHARPE_LIMIT,
            "poor_rr_threshold": self.POOR_RR_THRESHOLD,
            "alert_interval": self.PERFORMANCE_ALERT_INTERVAL
        }

    def validate_atr_compatibility(self) -> List[str]:
        """Валидация совместимости ATR параметров между модулями"""
        warnings = []
        
        # Проверяем разумность периода ATR
        if self.ATR_PERIOD < 5:
            warnings.append(f"ATR_PERIOD={self.ATR_PERIOD} слишком мал, рекомендуется >= 5")
        elif self.ATR_PERIOD > 50:
            warnings.append(f"ATR_PERIOD={self.ATR_PERIOD} слишком велик, рекомендуется <= 50")

        # Проверяем совместимость с интервалом логирования
        if self.INFO_LOG_INTERVAL_SEC < self.ANALYSIS_INTERVAL * 60:
            warnings.append("INFO_LOG_INTERVAL_SEC меньше торгового цикла - может быть много логов")

        # Проверяем совместимость с таймфреймом
        timeframe_minutes = self._parse_timeframe_to_minutes(self.TIMEFRAME)
        if timeframe_minutes and self.ATR_PERIOD * timeframe_minutes > 24 * 60:  # > 1 день
            warnings.append(f"ATR период покрывает > 1 дня данных при таймфрейме {self.TIMEFRAME}")

        return warnings

    def _parse_timeframe_to_minutes(self, timeframe: str) -> int:
        """Конвертировать таймфрейм в минуты"""
        try:
            if timeframe.endswith('m'):
                return int(timeframe[:-1])
            elif timeframe.endswith('h'):
                return int(timeframe[:-1]) * 60
            elif timeframe.endswith('d'):
                return int(timeframe[:-1]) * 24 * 60
            else:
                return 0
        except ValueError:
            return 0

    def summary(self) -> str:
        """Получить сводку конфигурации для логов"""
        return f"""
🔧 Trading Bot Configuration Summary:
├── Symbol: {self.SYMBOL} | Timeframe: {self.TIMEFRAME}
├── Position Size: ${self.POSITION_SIZE_USD} | Safe Mode: {self.SAFE_MODE}
├── AI Enabled: {self.AI_ENABLE} | Min Score: {self.MIN_SCORE_TO_BUY}
├── ✅ UNIFIED ATR: Period={self.ATR_PERIOD} | Method={self.RISK_ATR_METHOD}
├── Stop Loss: {self.STOP_LOSS_PCT}% | Take Profit: {self.TAKE_PROFIT_PCT}%
├── Webhook: {self.ENABLE_WEBHOOK} | Trading: {self.ENABLE_TRADING}
└── Logs: {self.LOG_LEVEL} | Info Interval: {self.INFO_LOG_INTERVAL_SEC}s
        """.strip()

# Создаём директории при старте, чтобы избежать FileNotFoundError
cfg = TradingConfig()

# Безопасное создание директорий
os.makedirs(os.path.dirname(cfg.CLOSED_TRADES_CSV) or ".", exist_ok=True)
os.makedirs(os.path.dirname(cfg.SIGNALS_CSV) or ".", exist_ok=True)
os.makedirs(cfg.LOGS_DIR, exist_ok=True)
os.makedirs(cfg.MODEL_DIR, exist_ok=True)

# Экспортируем для других модулей (обратная совместимость)
CLOSED_TRADES_CSV = cfg.CLOSED_TRADES_CSV
SIGNALS_CSV = cfg.SIGNALS_CSV
MODEL_DIR = cfg.MODEL_DIR
LOGS_DIR = cfg.LOGS_DIR

# ✅ НОВЫЙ ЭКСПОРТ: Unified ATR конфигурация
ATR_PERIOD = cfg.ATR_PERIOD
RISK_ATR_METHOD = cfg.RISK_ATR_METHOD
RISK_ATR_COMPARE = cfg.RISK_ATR_COMPARE
INFO_LOG_INTERVAL_SEC = cfg.INFO_LOG_INTERVAL_SEC