"""
Risk policies and base interfaces for risk rules.
Определяет контракты для всех правил риска и дефолтные политики.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from crypto_ai_bot.utils.decimal import dec


# ============= ENUMS =============

class RiskAction(Enum):
    """Действия по результатам проверки риска"""
    ALLOW = "allow"           # Разрешить операцию
    BLOCK = "block"           # Заблокировать операцию  
    REDUCE = "reduce"         # Уменьшить размер позиции
    WARNING = "warning"       # Предупреждение (логировать, но разрешить)


class RiskSeverity(Enum):
    """Уровень серьезности риска"""
    CRITICAL = "critical"     # Критический - полная остановка торговли
    HIGH = "high"            # Высокий - блокировать новые входы
    MEDIUM = "medium"        # Средний - уменьшить размер позиции
    LOW = "low"              # Низкий - только логирование
    INFO = "info"            # Информационный - мониторинг


# ============= DATA CLASSES =============

@dataclass
class RiskContext:
    """Контекст для проверки риска"""
    symbol: str
    amount: Decimal
    price: Decimal
    side: str  # "buy" | "sell"
    
    # Состояние счета
    balance_quote: Decimal
    position_size: Decimal = dec("0")
    
    # История
    trades_today: int = 0
    loss_streak: int = 0
    daily_pnl: Decimal = dec("0")
    max_drawdown_pct: Decimal = dec("0")
    
    # Рыночные данные
    spread_pct: Decimal = dec("0")
    volatility: Decimal = dec("0")
    
    # Метаданные
    timestamp: datetime = None
    trace_id: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class RiskResult:
    """Результат проверки правила риска"""
    action: RiskAction
    rule_name: str
    severity: RiskSeverity = RiskSeverity.INFO
    
    # Детали
    reason: str = ""
    suggested_amount: Optional[Decimal] = None  # Для REDUCE действия
    reduction_factor: Decimal = dec("1.0")  # На сколько уменьшить (0.5 = 50%)
    
    # Метрики
    score: Decimal = dec("0")  # Скоринг риска (0-100)
    threshold: Optional[Decimal] = None  # Порог срабатывания
    current_value: Optional[Decimal] = None  # Текущее значение
    
    # Метаданные
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Валидация reduction_factor для REDUCE действий
        if self.action == RiskAction.REDUCE:
            # Клампинг в диапазон [0, 1]
            self.reduction_factor = max(dec("0"), min(dec("1"), self.reduction_factor))
    
    @property
    def is_blocking(self) -> bool:
        """Блокирует ли операцию"""
        return self.action == RiskAction.BLOCK
    
    @property
    def is_reducing(self) -> bool:
        """Требует ли уменьшения позиции"""
        return self.action == RiskAction.REDUCE


# ============= BASE INTERFACES =============

class BaseRiskRule(ABC):
    """
    Базовый класс для всех правил риска.
    Каждое правило проверяет один аспект риска.
    """
    
    def __init__(self, name: str, enabled: bool = True):
        """
        Args:
            name: Уникальное имя правила
            enabled: Включено ли правило
        """
        self.name = name
        self.enabled = enabled
    
    @abstractmethod
    async def check(self, context: RiskContext) -> RiskResult:
        """
        Проверить правило риска.
        
        Args:
            context: Контекст с информацией о сделке и состоянии
            
        Returns:
            RiskResult с действием и деталями
        """
        ...
    
    @abstractmethod
    def get_severity(self) -> RiskSeverity:
        """Получить уровень серьезности правила"""
        ...
    
    def is_enabled(self) -> bool:
        """Включено ли правило"""
        return self.enabled
    
    def disable(self) -> None:
        """Отключить правило"""
        self.enabled = False
    
    def enable(self) -> None:
        """Включить правило"""
        self.enabled = True


class CriticalRiskRule(BaseRiskRule):
    """Критическое правило - блокирует ВСЮ торговлю при срабатывании"""
    
    def get_severity(self) -> RiskSeverity:
        return RiskSeverity.CRITICAL


class HardRiskRule(BaseRiskRule):
    """Жесткое правило - блокирует новые входы при срабатывании"""
    
    def get_severity(self) -> RiskSeverity:
        return RiskSeverity.HIGH


class SoftRiskRule(BaseRiskRule):
    """Мягкое правило - уменьшает размер позиции при срабатывании"""
    
    def get_severity(self) -> RiskSeverity:
        return RiskSeverity.MEDIUM


class MonitoringRule(BaseRiskRule):
    """Правило мониторинга - только логирует, не блокирует"""
    
    def get_severity(self) -> RiskSeverity:
        return RiskSeverity.INFO


# ============= DEFAULT POLICIES =============

@dataclass
class SoftRiskDefaults:
    """
    Мягкие риск-лимиты (из кода, могут быть переопределены через ENV).
    Эти правила обычно приводят к уменьшению позиции, а не блокировке.
    """
    # Временные ограничения
    COOLDOWN_SEC: int = 60  # Пауза между сделками
    
    # Рыночные условия
    MAX_SPREAD_PCT: Decimal = dec("0.5")  # Максимальный спред
    MAX_SLIPPAGE_PCT: Decimal = dec("1.0")  # Максимальное проскальзывание
    
    # Частота торговли
    MAX_ORDERS_5M: int = 5  # Максимум ордеров за 5 минут
    MAX_TURNOVER_5M_QUOTE: Decimal = dec("1000.0")  # Максимальный оборот за 5 минут
    
    # Комиссии
    FEE_PCT_ESTIMATE: Decimal = dec("0.1")  # Оценка комиссии биржи


@dataclass
class HardRiskDefaults:
    """
    Жесткие риск-лимиты (критические).
    При превышении - полная остановка торговли.
    """
    # Критические лимиты убытков
    MAX_DRAWDOWN_PCT: Decimal = dec("10.0")  # Максимальная просадка
    DAILY_LOSS_LIMIT_QUOTE: Decimal = dec("100.0")  # Дневной лимит убытков
    LOSS_STREAK_COUNT: int = 3  # Максимальная серия убыточных сделок
    
    # Размер позиции
    MAX_POSITION_PCT: Decimal = dec("80.0")  # Максимум % от баланса в позиции
    MIN_BALANCE_QUOTE: Decimal = dec("10.0")  # Минимальный баланс для торговли


@dataclass
class RiskScoring:
    """Параметры для расчета риск-скоринга"""
    # Веса для разных факторов риска (сумма = 1.0)
    WEIGHT_DRAWDOWN: float = 0.30
    WEIGHT_LOSS_STREAK: float = 0.25
    WEIGHT_DAILY_LOSS: float = 0.20
    WEIGHT_SPREAD: float = 0.10
    WEIGHT_VOLATILITY: float = 0.10
    WEIGHT_POSITION_SIZE: float = 0.05
    
    def calculate_score(self, context: RiskContext, hard_limits: HardRiskDefaults) -> Decimal:
        """
        Рассчитать общий риск-скор (0-100).
        0 = минимальный риск, 100 = максимальный риск
        """
        score = dec("0")
        
        # Drawdown компонент
        if hard_limits.MAX_DRAWDOWN_PCT > 0:
            drawdown_ratio = context.max_drawdown_pct / hard_limits.MAX_DRAWDOWN_PCT
            score += dec(str(self.WEIGHT_DRAWDOWN)) * min(dec("100"), drawdown_ratio * 100)
        
        # Loss streak компонент
        if hard_limits.LOSS_STREAK_COUNT > 0:
            streak_ratio = dec(str(context.loss_streak)) / dec(str(hard_limits.LOSS_STREAK_COUNT))
            score += dec(str(self.WEIGHT_LOSS_STREAK)) * min(dec("100"), streak_ratio * 100)
        
        # Daily loss компонент
        if hard_limits.DAILY_LOSS_LIMIT_QUOTE > 0:
            daily_loss_ratio = abs(context.daily_pnl) / hard_limits.DAILY_LOSS_LIMIT_QUOTE
            score += dec(str(self.WEIGHT_DAILY_LOSS)) * min(dec("100"), daily_loss_ratio * 100)
        
        # Spread компонент (нормализуем к 0-100)
        spread_score = min(dec("100"), context.spread_pct * 20)  # 5% spread = 100 score
        score += dec(str(self.WEIGHT_SPREAD)) * spread_score
        
        # Volatility компонент
        vol_score = min(dec("100"), context.volatility)  # Предполагаем volatility уже в %
        score += dec(str(self.WEIGHT_VOLATILITY)) * vol_score
        
        # Position size компонент
        if context.balance_quote > 0:
            position_pct = (context.position_size * context.price) / context.balance_quote * 100
            position_score = min(dec("100"), position_pct)
            score += dec(str(self.WEIGHT_POSITION_SIZE)) * position_score
        
        return min(dec("100"), max(dec("0"), score))


# ============= FACTORY =============

def create_default_soft_limits() -> SoftRiskDefaults:
    """Создать дефолтные мягкие лимиты"""
    return SoftRiskDefaults()


def create_default_hard_limits() -> HardRiskDefaults:
    """Создать дефолтные жесткие лимиты"""
    return HardRiskDefaults()


def create_risk_scorer() -> RiskScoring:
    """Создать калькулятор риск-скоринга"""
    return RiskScoring()


# ============= EXPORT =============

__all__ = [
    # Enums
    "RiskAction",
    "RiskSeverity",
    
    # Data classes
    "RiskContext",
    "RiskResult",
    
    # Base classes
    "BaseRiskRule",
    "CriticalRiskRule",
    "HardRiskRule",
    "SoftRiskRule",
    "MonitoringRule",
    
    # Policies
    "SoftRiskDefaults",
    "HardRiskDefaults",
    "RiskScoring",
    
    # Factory functions
    "create_default_soft_limits",
    "create_default_hard_limits",
    "create_risk_scorer",
]