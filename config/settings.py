import os
from dataclasses import dataclass
from typing import List, Optional
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
    """Единая конфигурация для всего торгового бота"""
    
    # ==== Telegram ====
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHAT_ID: str = os.getenv("CHAT_ID", "")
    ADMIN_CHAT_IDS: List[str] = getenv_list("ADMIN_CHAT_IDS", [])
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
    TEST_TRADE_AMOUNT: float = getenv_float("TEST_TRADE_AMOUNT", 3.0)
    
    # ==== Скоринг и AI ====
    MIN_SCORE_TO_BUY: float = getenv_float("MIN_SCORE_TO_BUY", 0.65)
    AI_MIN_TO_TRADE: float = getenv_float("AI_MIN_TO_TRADE", 0.70)
    AI_ENABLE: bool = getenv_bool("AI_ENABLE", True)
    AI_FAILOVER_SCORE: float = getenv_float("AI_FAILOVER_SCORE", 0.55)
    ENFORCE_AI_GATE: bool = getenv_bool("ENFORCE_AI_GATE", True)
    
    # ==== Риск-менеджмент ====
    STOP_LOSS_PCT: float = getenv_float("STOP_LOSS_PCT", 2.0)
    TAKE_PROFIT_PCT: float = getenv_float("TAKE_PROFIT_PCT", 1.5)
    POSITION_MIN_FRACTION: float = getenv_float("POSITION_MIN_FRACTION", 0.30)
    POSITION_MAX_FRACTION: float = getenv_float("POSITION_MAX_FRACTION", 1.00)
    POST_SALE_COOLDOWN: int = getenv_int("POST_SALE_COOLDOWN", 60)
    
    # ==== Продвинутые Take Profit (упрощенная версия) ====
    TP1_PCT: float = getenv_float("TP1_PCT", 0.5)
    TP2_PCT: float = getenv_float("TP2_PCT", 1.0)
    TP1_SIZE: float = getenv_float("TP1_SIZE", 0.5)
    TP2_SIZE: float = getenv_float("TP2_SIZE", 0.5)
    TRAILING_STOP_ENABLE: bool = getenv_bool("TRAILING_STOP_ENABLE", True)
    TRAILING_STOP_PCT: float = getenv_float("TRAILING_STOP_PCT", 0.5)
    
    # ==== Файлы и пути ====
    MODEL_DIR: str = os.getenv("MODEL_DIR", "models")
    CLOSED_TRADES_CSV: str = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
    SIGNALS_CSV: str = os.getenv("SIGNALS_CSV", "signals_snapshots.csv")
    LOGS_DIR: str = os.getenv("LOGS_DIR", "logs")
    
    # ==== Webhook ====
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    
    # ==== Дополнительные настройки ====
    COMMAND_COOLDOWN: int = getenv_int("COMMAND_COOLDOWN", 3)
    
    def validate_config(self) -> List[str]:
        """Валидация конфигурации и возврат списка ошибок"""
        errors = []
        
        # Критические поля
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN не задан")
        if not self.CHAT_ID:
            errors.append("CHAT_ID не задан")
        if not self.GATE_API_KEY:
            errors.append("GATE_API_KEY не задан")
        if not self.GATE_API_SECRET:
            errors.append("GATE_API_SECRET не задан")
            
        # Webhook
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
            
        # Риски
        if self.STOP_LOSS_PCT <= 0:
            errors.append("STOP_LOSS_PCT должен быть > 0")
        if self.TAKE_PROFIT_PCT <= 0:
            errors.append("TAKE_PROFIT_PCT должен быть > 0")
            
        return errors
    
    def get_webhook_url(self) -> str:
        """Полный URL webhook'а"""
        if not self.PUBLIC_URL or not self.WEBHOOK_SECRET:
            return ""
        return f"{self.PUBLIC_URL.rstrip('/')}/webhook/{self.WEBHOOK_SECRET}"
    
    def is_admin(self, chat_id: str) -> bool:
        """Проверка является ли пользователь админом"""
        return str(chat_id) in self.ADMIN_CHAT_IDS
    
    def get_tp_levels(self) -> List[dict]:
        """Возвращает упрощенные уровни TP"""
        return [
            {"level": 1, "pct": self.TP1_PCT, "size": self.TP1_SIZE},
            {"level": 2, "pct": self.TP2_PCT, "size": self.TP2_SIZE}
        ]