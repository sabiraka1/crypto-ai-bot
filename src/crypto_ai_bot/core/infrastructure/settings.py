"""
Settings module for crypto-ai-bot.
Единый источник конфигурации системы.

Философия:
- ENV = только критичное (среда, безопасность, ключевые лимиты)
- Код = умные дефолты, адаптивная логика, политики
- Override = ENV может переопределить дефолты из кода
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from crypto_ai_bot.utils.decimal import dec


# ============= ДЕФОЛТЫ ИЗ КОДА (не ENV) =============

@dataclass
class BackgroundIntervals:
    """Интервалы фоновых процессов (секунды)"""
    EVAL: int = 15            # Оценка сигналов
    EXITS: int = 5             # Проверка защитных выходов
    RECONCILE: int = 60        # Сверка с биржей
    SETTLEMENT: int = 30       # Обработка частичных исполнений
    WATCHDOG: int = 3          # Мониторинг здоровья
    HEALTH_CHECK: int = 10     # HTTP health endpoint


@dataclass
class SoftRiskDefaults:
    """Мягкие риск-правила (из кода, не ENV)"""
    COOLDOWN_SEC: int = 60
    MAX_SPREAD_PCT: Decimal = dec("0.5")
    MAX_SLIPPAGE_PCT: Decimal = dec("1.0")
    MAX_ORDERS_5M: int = 5
    MAX_TURNOVER_5M_QUOTE: Decimal = dec("1000.0")
    FEE_PCT_ESTIMATE: Decimal = dec("0.1")  # 0.1% комиссия биржи


@dataclass
class TechnicalDefaults:
    """Технические параметры"""
    BROKER_RATE_RPS: float = 8.0
    BROKER_RATE_BURST: int = 16
    HTTP_TIMEOUT_SEC: int = 30
    IDEMPOTENCY_BUCKET_MS: int = 60000
    IDEMPOTENCY_TTL_SEC: int = 3600
    BACKUP_RETENTION_DAYS: int = 30
    
    # Dead Man's Switch
    DMS_TIMEOUT_MS: int = 120000  # 2 минуты
    DMS_RECHECKS: int = 2
    DMS_RECHECK_DELAY_SEC: float = 3.0
    DMS_MAX_IMPACT_PCT: Decimal = dec("1.0")


@dataclass
class RegimeDefaults:
    """Дефолтные пороги для режима рынка"""
    DXY_CHANGE_PCT: Decimal = dec("0.35")
    BTC_DOM_CHANGE_PCT: Decimal = dec("0.60")
    FOMC_BLOCK_HOURS: int = 8
    HTTP_TIMEOUT_SEC: float = 5.0


@dataclass 
class StrategyWeights:
    """Веса стратегий и таймфреймов (с авто-нормализацией)"""
    # Базовые веса таймфреймов
    MTF_15M: float = 0.40  # Основной торговый ТФ
    MTF_1H: float = 0.25
    MTF_4H: float = 0.20
    MTF_1D: float = 0.10
    MTF_1W: float = 0.05
    
    # Fusion веса
    TECHNICAL: float = 0.65
    AI: float = 0.35
    
    def normalize_mtf_weights(self) -> dict[str, float]:
        """Нормализовать веса таймфреймов (сумма = 1.0)"""
        weights = {
            '15m': self.MTF_15M,
            '1h': self.MTF_1H,
            '4h': self.MTF_4H,
            '1d': self.MTF_1D,
            '1w': self.MTF_1W
        }
        total = sum(weights.values())
        if total > 0:
            return {k: v/total for k, v in weights.items()}
        return weights
    
    def normalize_fusion_weights(self) -> tuple[float, float]:
        """Нормализовать веса fusion (сумма = 1.0)"""
        total = self.TECHNICAL + self.AI
        if total > 0:
            return self.TECHNICAL/total, self.AI/total
        return 1.0, 0.0  # Fallback: только технический


# ============= HELPERS =============

def _get_env(name: str, default: str = "") -> str:
    """Получить значение из ENV"""
    return os.getenv(name, default).strip()


def _get_bool(name: str, default: bool = False) -> bool:
    """ENV переменная как bool"""
    val = _get_env(name, str(default))
    return val.lower() in ('1', 'true', 'yes', 'on')


def _get_int(name: str, default: int = 0) -> int:
    """ENV переменная как int"""
    val = _get_env(name, str(default))
    try:
        return int(val) if val else default
    except ValueError:
        return default


def _get_float(name: str, default: float = 0.0) -> float:
    """ENV переменная как float"""
    val = _get_env(name, str(default))
    try:
        return float(val) if val else default
    except ValueError:
        return default


def _get_decimal(name: str, default: str = "0") -> Decimal:
    """ENV переменная как Decimal (для денег и процентов)"""
    val = _get_env(name, default)
    try:
        return dec(val) if val else dec(default)
    except Exception:
        return dec(default)


def _get_list(name: str, default: str = "") -> list[str]:
    """ENV переменная как список строк (через запятую)"""
    raw = _get_env(name, default)
    return [s.strip() for s in raw.split(',') if s.strip()]


def _get_int_list(name: str, default: str = "") -> list[int]:
    """ENV переменная как список int (через запятую)"""
    raw = _get_env(name, default)
    result = []
    for s in raw.split(','):
        s = s.strip()
        if s and s.isdigit():
            result.append(int(s))
    return result


def _get_secret(name: str, default: str = "") -> str:
    """
    Получить секрет (API ключи и т.д.)
    Поддержка _FILE суффикса для чтения из файла
    """
    # Сначала проверяем файл
    file_path = _get_env(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except Exception:
            pass
    
    # Иначе обычный ENV
    return _get_env(name, default)


def _get_config_value(env_name: str, default_value):
    """
    Приоритет загрузки:
    1. ENV переменная (если задана)
    2. Дефолт из кода
    """
    env_val = _get_env(env_name)
    if env_val:
        # Определяем тип по дефолту
        if isinstance(default_value, bool):
            return _get_bool(env_name)
        elif isinstance(default_value, int):
            return _get_int(env_name, default_value)
        elif isinstance(default_value, float):
            return _get_float(env_name, default_value)
        elif isinstance(default_value, Decimal):
            return _get_decimal(env_name, str(default_value))
        else:
            return env_val
    return default_value


# ============= ОСНОВНОЙ КЛАСС НАСТРОЕК =============

@dataclass
class Settings:
    """
    Единый источник конфигурации системы.
    
    Структура:
    - Критичные параметры из ENV (обязательные)
    - Умные дефолты из кода (опциональные override через ENV)
    - Вычисляемые значения
    """
    
    # ========== КРИТИЧНЫЕ (из ENV) ==========
    
    # --- Среда и режим ---
    MODE: str  # paper | live - ОБЯЗАТЕЛЬНО
    EXCHANGE: str  # gateio - ОБЯЗАТЕЛЬНО  
    SYMBOLS: list[str]  # ['BTC/USDT', 'ETH/USDT'] - ОБЯЗАТЕЛЬНО
    
    # --- API доступ (для live) ---
    API_KEY: str = ""
    API_SECRET: str = ""
    API_TOKEN: str = ""  # Для HTTP API endpoints
    
    # --- Критичные торговые параметры ---
    FIXED_AMOUNT: Decimal = dec("50.0")  # Размер позиции в USDT
    
    # Защитные выходы (в процентах)
    STOP_LOSS_PCT: Decimal = dec("5.0")
    TRAILING_STOP_PCT: Decimal = dec("3.0")
    TAKE_PROFIT_1_PCT: Decimal = dec("2.0")  # Закрыть 50%
    TAKE_PROFIT_2_PCT: Decimal = dec("5.0")  # Закрыть остаток
    
    # Критические риск-лимиты
    RISK_MAX_DRAWDOWN_PCT: Decimal = dec("10.0")
    RISK_DAILY_LOSS_LIMIT_QUOTE: Decimal = dec("100.0")
    RISK_LOSS_STREAK_COUNT: int = 3
    
    # --- Внешние сервисы (опционально) ---
    
    # Telegram
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_ALLOWED_USERS: list[int] = field(default_factory=list)
    
    # Макро-источники (URLs only)
    REGIME_ENABLED: bool = False
    REGIME_DXY_URL: str = ""
    REGIME_BTC_DOM_URL: str = ""
    REGIME_FOMC_URL: str = ""
    
    # Инфраструктура
    EVENT_BUS_URL: str = ""  # "" = in-memory, "redis://..." = Redis
    DB_PATH: str = ""  # Будет вычислен автоматически
    LOG_LEVEL: str = "INFO"
    
    # ========== ДЕФОЛТЫ ИЗ КОДА (редко override) ==========
    
    # Фоновые процессы
    intervals: BackgroundIntervals = field(default_factory=BackgroundIntervals)
    
    # Мягкие риск-правила  
    soft_risk: SoftRiskDefaults = field(default_factory=SoftRiskDefaults)
    
    # Технические параметры
    technical: TechnicalDefaults = field(default_factory=TechnicalDefaults)
    
    # Режим рынка (дефолты)
    regime: RegimeDefaults = field(default_factory=RegimeDefaults)
    
    # Веса стратегий
    weights: StrategyWeights = field(default_factory=StrategyWeights)
    
    # ========== ВЫЧИСЛЯЕМЫЕ ЗНАЧЕНИЯ ==========
    
    # Runtime info
    POD_NAME: str = field(init=False)
    HOSTNAME: str = field(init=False)
    SESSION_ID: str = field(init=False)
    
    # Флаги включения подсистем
    AUTOSTART: bool = field(init=False)
    EVAL_ENABLED: bool = field(init=False)
    EXITS_ENABLED: bool = field(init=False)
    RECONCILE_ENABLED: bool = field(init=False)
    SETTLEMENT_ENABLED: bool = field(init=False)
    WATCHDOG_ENABLED: bool = field(init=False)
    DMS_ENABLED: bool = field(init=False)
    
    # Режим выходов
    EXITS_MODE: str = field(init=False)  # "stop" | "trailing" | "both"
    
    def __post_init__(self):
        """Вычисляемые значения и финальная валидация"""
        import socket
        import uuid
        
        # Runtime
        self.POD_NAME = _get_env("POD_NAME", "local")
        self.HOSTNAME = _get_env("HOSTNAME", socket.gethostname())
        self.SESSION_ID = _get_env("SESSION_ID", str(uuid.uuid4())[:8])
        
        # Автоматический путь к БД если не задан
        if not self.DB_PATH:
            symbol = self.SYMBOLS[0] if self.SYMBOLS else "BTC-USDT"
            base, quote = symbol.replace("/", "-").split("-")
            self.DB_PATH = f"./data/trader-{self.EXCHANGE}-{base}{quote}-{self.MODE}.sqlite3"
        
        # Флаги подсистем (можно отключить через ENV для отладки)
        self.AUTOSTART = _get_bool("AUTOSTART", self.MODE == "paper")
        self.EVAL_ENABLED = _get_bool("EVAL_ENABLED", True)
        self.EXITS_ENABLED = _get_bool("EXITS_ENABLED", True)
        self.RECONCILE_ENABLED = _get_bool("RECONCILE_ENABLED", True)
        self.SETTLEMENT_ENABLED = _get_bool("SETTLEMENT_ENABLED", True)
        self.WATCHDOG_ENABLED = _get_bool("WATCHDOG_ENABLED", True)
        self.DMS_ENABLED = _get_bool("DMS_ENABLED", self.MODE == "live")
        
        # Режим выходов
        self.EXITS_MODE = _get_env("EXITS_MODE", "both")  # stop | trailing | both
        
        # Override интервалов из ENV если заданы
        self.intervals.EVAL = _get_config_value("EVAL_INTERVAL_SEC", self.intervals.EVAL)
        self.intervals.EXITS = _get_config_value("EXITS_INTERVAL_SEC", self.intervals.EXITS)
        self.intervals.RECONCILE = _get_config_value("RECONCILE_INTERVAL_SEC", self.intervals.RECONCILE)
        self.intervals.SETTLEMENT = _get_config_value("SETTLEMENT_INTERVAL_SEC", self.intervals.SETTLEMENT)
        self.intervals.WATCHDOG = _get_config_value("WATCHDOG_INTERVAL_SEC", self.intervals.WATCHDOG)
        
        # Override мягких правил если заданы
        self.soft_risk.COOLDOWN_SEC = _get_config_value("RISK_COOLDOWN_SEC", self.soft_risk.COOLDOWN_SEC)
        self.soft_risk.MAX_SPREAD_PCT = _get_config_value("RISK_MAX_SPREAD_PCT", self.soft_risk.MAX_SPREAD_PCT)
        self.soft_risk.MAX_SLIPPAGE_PCT = _get_config_value("RISK_MAX_SLIPPAGE_PCT", self.soft_risk.MAX_SLIPPAGE_PCT)
        self.soft_risk.MAX_ORDERS_5M = _get_config_value("RISK_MAX_ORDERS_5M", self.soft_risk.MAX_ORDERS_5M)
        self.soft_risk.MAX_TURNOVER_5M_QUOTE = _get_config_value("RISK_MAX_TURNOVER_5M_QUOTE", self.soft_risk.MAX_TURNOVER_5M_QUOTE)
        
        # Override режима если заданы
        self.regime.DXY_CHANGE_PCT = _get_config_value("REGIME_DXY_LIMIT_PCT", self.regime.DXY_CHANGE_PCT)
        self.regime.BTC_DOM_CHANGE_PCT = _get_config_value("REGIME_BTC_DOM_LIMIT_PCT", self.regime.BTC_DOM_CHANGE_PCT)
        self.regime.FOMC_BLOCK_HOURS = _get_config_value("REGIME_FOMC_BLOCK_HOURS", self.regime.FOMC_BLOCK_HOURS)
        
        # Override весов если заданы
        self.weights.MTF_15M = _get_config_value("MTF_W_M15", self.weights.MTF_15M)
        self.weights.MTF_1H = _get_config_value("MTF_W_H1", self.weights.MTF_1H)
        self.weights.MTF_4H = _get_config_value("MTF_W_H4", self.weights.MTF_4H)
        self.weights.MTF_1D = _get_config_value("MTF_W_D1", self.weights.MTF_1D)
        self.weights.MTF_1W = _get_config_value("MTF_W_W1", self.weights.MTF_1W)
        self.weights.TECHNICAL = _get_config_value("FUSION_W_TECHNICAL", self.weights.TECHNICAL)
        self.weights.AI = _get_config_value("FUSION_W_AI", self.weights.AI)
        
        # Override DMS если заданы
        self.technical.DMS_TIMEOUT_MS = _get_config_value("DMS_TIMEOUT_MS", self.technical.DMS_TIMEOUT_MS)
        self.technical.DMS_RECHECKS = _get_config_value("DMS_RECHECKS", self.technical.DMS_RECHECKS)
        self.technical.DMS_RECHECK_DELAY_SEC = _get_config_value("DMS_RECHECK_DELAY_SEC", self.technical.DMS_RECHECK_DELAY_SEC)
        
        # Валидация
        self._validate()
    
    def _validate(self):
        """Валидация критичных параметров"""
        # Обязательные
        assert self.MODE in ("paper", "live"), f"MODE должен быть paper или live, получен {self.MODE}"
        assert self.EXCHANGE, "EXCHANGE обязателен"
        assert self.SYMBOLS, "SYMBOLS обязателен (минимум одна пара)"
        
        # API ключи для live
        if self.MODE == "live":
            assert self.API_KEY, "API_KEY обязателен для live режима"
            assert self.API_SECRET, "API_SECRET обязателен для live режима"
        
        # Критические лимиты
        assert self.FIXED_AMOUNT > 0, "FIXED_AMOUNT должен быть > 0"
        assert self.RISK_MAX_DRAWDOWN_PCT > 0, "RISK_MAX_DRAWDOWN_PCT должен быть > 0"
        assert self.RISK_DAILY_LOSS_LIMIT_QUOTE > 0, "RISK_DAILY_LOSS_LIMIT_QUOTE должен быть > 0"
        
        # Защитные выходы
        assert 0 < self.STOP_LOSS_PCT <= 100, "STOP_LOSS_PCT должен быть от 0 до 100"
        assert 0 < self.TRAILING_STOP_PCT <= 100, "TRAILING_STOP_PCT должен быть от 0 до 100"
        assert 0 < self.TAKE_PROFIT_1_PCT <= 100, "TAKE_PROFIT_1_PCT должен быть от 0 до 100"
        assert 0 < self.TAKE_PROFIT_2_PCT <= 100, "TAKE_PROFIT_2_PCT должен быть от 0 до 100"
        
        # Режим выходов
        assert self.EXITS_MODE in ("stop", "trailing", "both"), f"EXITS_MODE должен быть stop|trailing|both, получен {self.EXITS_MODE}"
        
        # Telegram
        if self.TELEGRAM_ENABLED:
            assert self.TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN обязателен если Telegram включен"
            assert self.TELEGRAM_CHAT_ID, "TELEGRAM_CHAT_ID обязателен если Telegram включен"
        
        # Интервалы должны быть положительными
        assert self.intervals.EVAL > 0, "EVAL_INTERVAL_SEC должен быть > 0"
        assert self.intervals.EXITS > 0, "EXITS_INTERVAL_SEC должен быть > 0"
        assert self.intervals.RECONCILE > 0, "RECONCILE_INTERVAL_SEC должен быть > 0"
    
    @classmethod
    def load(cls) -> "Settings":
        """Загрузить настройки из ENV с валидацией"""
        
        settings = cls(
            # Критичные из ENV
            MODE=_get_env("MODE", "paper"),
            EXCHANGE=_get_env("EXCHANGE", "gateio"),
            SYMBOLS=_get_list("SYMBOLS", "BTC/USDT"),
            
            # API
            API_KEY=_get_secret("API_KEY"),
            API_SECRET=_get_secret("API_SECRET"),
            API_TOKEN=_get_env("API_TOKEN"),
            
            # Торговые параметры (Decimal для точности)
            FIXED_AMOUNT=_get_decimal("FIXED_AMOUNT", "50.0"),
            
            # Защитные выходы (Decimal для процентов)
            STOP_LOSS_PCT=_get_decimal("STOP_LOSS_PCT", "5.0"),
            TRAILING_STOP_PCT=_get_decimal("TRAILING_STOP_PCT", "3.0"),
            TAKE_PROFIT_1_PCT=_get_decimal("TAKE_PROFIT_1_PCT", "2.0"),
            TAKE_PROFIT_2_PCT=_get_decimal("TAKE_PROFIT_2_PCT", "5.0"),
            
            # Критические риски (Decimal для денег и процентов)
            RISK_MAX_DRAWDOWN_PCT=_get_decimal("RISK_MAX_DRAWDOWN_PCT", "10.0"),
            RISK_DAILY_LOSS_LIMIT_QUOTE=_get_decimal("RISK_DAILY_LOSS_LIMIT_QUOTE", "100.0"),
            RISK_LOSS_STREAK_COUNT=_get_int("RISK_LOSS_STREAK_COUNT", 3),
            
            # Telegram
            TELEGRAM_ENABLED=_get_bool("TELEGRAM_ENABLED"),
            TELEGRAM_BOT_TOKEN=_get_secret("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_CHAT_ID=_get_env("TELEGRAM_CHAT_ID"),
            TELEGRAM_ALLOWED_USERS=_get_int_list("TELEGRAM_ALLOWED_USERS"),
            
            # Режим рынка
            REGIME_ENABLED=_get_bool("REGIME_ENABLED"),
            REGIME_DXY_URL=_get_env("REGIME_DXY_URL"),
            REGIME_BTC_DOM_URL=_get_env("REGIME_BTC_DOM_URL"),
            REGIME_FOMC_URL=_get_env("REGIME_FOMC_URL"),
            
            # Инфраструктура
            EVENT_BUS_URL=_get_env("EVENT_BUS_URL"),
            DB_PATH=_get_env("DB_PATH"),
            LOG_LEVEL=_get_env("LOG_LEVEL", "INFO"),
        )
        
        return settings
    
    def get_normalized_mtf_weights(self) -> dict[str, float]:
        """Получить нормализованные веса таймфреймов"""
        return self.weights.normalize_mtf_weights()
    
    def get_normalized_fusion_weights(self) -> tuple[float, float]:
        """Получить нормализованные веса fusion (technical, ai)"""
        return self.weights.normalize_fusion_weights()


# ============= SINGLETON =============

_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """Получить единственный экземпляр настроек"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings.load()
    return _settings_instance


def reload_settings():
    """Перезагрузить настройки (для тестов)"""
    global _settings_instance
    _settings_instance = None
    return get_settings()


# ============= EXPORT =============

__all__ = [
    "Settings",
    "get_settings", 
    "reload_settings",
    "BackgroundIntervals",
    "SoftRiskDefaults",
    "TechnicalDefaults",
    "RegimeDefaults",
    "StrategyWeights",
]