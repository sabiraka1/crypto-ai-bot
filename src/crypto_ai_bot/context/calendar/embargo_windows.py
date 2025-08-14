# embargo_windows.py - Система торговых ограничений
"""
🚫 Trading Embargo Windows - управление временными ограничениями торговли

Интеграция с существующей архитектурой:
- Используется в SignalValidator для блокировки сигналов
- Интегрируется с TradingBot через временные проверки
- Поддерживает настройки через Settings
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EmbargoReason(Enum):
    """Причины торгового эмбарго"""
    FOMC_MEETING = "fomc_meeting"
    ECONOMIC_DATA = "economic_data"
    LOW_LIQUIDITY = "low_liquidity"
    HIGH_VOLATILITY = "high_volatility"
    EXCHANGE_MAINTENANCE = "exchange_maintenance"
    MANUAL_OVERRIDE = "manual_override"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


@dataclass
class EmbargoWindow:
    """Временное окно торгового ограничения"""
    start: datetime
    end: datetime
    reason: EmbargoReason
    description: str
    severity: str = "BLOCK"  # BLOCK, WARN, REDUCE_SIZE
    affected_symbols: Optional[List[str]] = None  # None = все символы
    
    def is_active(self, timestamp: Optional[datetime] = None) -> bool:
        """Проверка активности окна ограничения"""
        now = timestamp or datetime.now(timezone.utc)
        return self.start <= now <= self.end
    
    def time_until_start(self, timestamp: Optional[datetime] = None) -> float:
        """Минуты до начала ограничения"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.start - now).total_seconds() / 60.0
    
    def time_until_end(self, timestamp: Optional[datetime] = None) -> float:
        """Минуты до окончания ограничения"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.end - now).total_seconds() / 60.0


class EmbargoManager:
    """
    Центральный менеджер торговых ограничений
    
    Интеграция:
    - В _validate_time_windows() SignalValidator
    - В TradingBot._tick() для проверки перед анализом
    - В PositionManager для экстренного закрытия при критических событиях
    """
    
    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings
        self.active_embargos: List[EmbargoWindow] = []
        self.scheduled_embargos: List[EmbargoWindow] = []
        
        # Настройки из Settings
        self.enable_fomc_embargo = getattr(settings, "ENABLE_FOMC_EMBARGO", True)
        self.enable_weekend_embargo = getattr(settings, "DISABLE_WEEKEND_TRADING", False)
        self.fomc_embargo_minutes = getattr(settings, "FOMC_EMBARGO_MINUTES", 30)
        self.high_volatility_threshold = getattr(settings, "HIGH_VOLATILITY_EMBARGO_THRESHOLD", 8.0)
        
        logger.info(f"🚫 EmbargoManager initialized: FOMC={self.enable_fomc_embargo}")
    
    # === Основной API ===
    def check_embargo_status(self, symbol: str = "BTC/USDT", 
                           timestamp: Optional[datetime] = None) -> Tuple[bool, List[str]]:
        """
        Главная функция проверки торговых ограничений
        
        Returns:
            (is_embargoed, reasons) - можно ли торговать и причины ограничений
        """
        now = timestamp or datetime.now(timezone.utc)
        reasons = []
        
        # Проверяем активные ограничения
        for embargo in self.active_embargos:
            if embargo.is_active(now):
                if not embargo.affected_symbols or symbol in embargo.affected_symbols:
                    if embargo.severity == "BLOCK":
                        reasons.append(f"{embargo.reason.value}: {embargo.description}")
        
        # Динамические проверки
        weekend_reason = self._check_weekend_embargo(now)
        if weekend_reason:
            reasons.append(weekend_reason)
            
        return len(reasons) > 0, reasons
    
    def get_next_embargo(self, symbol: str = "BTC/USDT") -> Optional[EmbargoWindow]:
        """Получить следующее ближайшее ограничение"""
        now = datetime.now(timezone.utc)
        upcoming = [e for e in self.scheduled_embargos 
                   if e.start > now and (not e.affected_symbols or symbol in e.affected_symbols)]
        return min(upcoming, key=lambda x: x.start) if upcoming else None
    
    # === Интеграция с FOMC ===
    def schedule_fomc_embargo(self, fomc_datetime: datetime, description: str = "FOMC Meeting"):
        """Планирование ограничений вокруг событий FOMC"""
        if not self.enable_fomc_embargo:
            return
            
        # Ограничение за 30 минут до и 15 минут после
        start = fomc_datetime - timedelta(minutes=self.fomc_embargo_minutes)
        end = fomc_datetime + timedelta(minutes=15)
        
        embargo = EmbargoWindow(
            start=start,
            end=end,
            reason=EmbargoReason.FOMC_MEETING,
            description=description,
            severity="BLOCK"
        )
        
        self.scheduled_embargos.append(embargo)
        logger.info(f"📅 FOMC embargo scheduled: {start} - {end}")
    
    # === Динамические ограничения ===
    def trigger_volatility_embargo(self, atr_pct: float, duration_minutes: int = 15):
        """Экстренное ограничение при высокой волатильности"""
        if atr_pct < self.high_volatility_threshold:
            return
            
        now = datetime.now(timezone.utc)
        embargo = EmbargoWindow(
            start=now,
            end=now + timedelta(minutes=duration_minutes),
            reason=EmbargoReason.HIGH_VOLATILITY,
            description=f"High volatility: ATR {atr_pct:.2f}%",
            severity="BLOCK"
        )
        
        self.active_embargos.append(embargo)
        logger.warning(f"🌪️ Volatility embargo triggered: ATR {atr_pct:.2f}%")
    
    def add_manual_embargo(self, minutes: int, reason: str):
        """Ручное ограничение торговли"""
        now = datetime.now(timezone.utc)
        embargo = EmbargoWindow(
            start=now,
            end=now + timedelta(minutes=minutes),
            reason=EmbargoReason.MANUAL_OVERRIDE,
            description=f"Manual: {reason}",
            severity="BLOCK"
        )
        
        self.active_embargos.append(embargo)
        logger.warning(f"✋ Manual embargo: {minutes}min - {reason}")
    
    # === Вспомогательные методы ===
    def _check_weekend_embargo(self, timestamp: datetime) -> Optional[str]:
        """Проверка выходных дней"""
        if not self.enable_weekend_embargo:
            return None
            
        if timestamp.weekday() >= 5:  # Суббота/Воскресенье
            return f"weekend_trading_disabled: {timestamp.strftime('%A')}"
        return None
    
    def cleanup_expired_embargos(self):
        """Очистка истекших ограничений"""
        now = datetime.now(timezone.utc)
        
        # Удаляем истекшие активные
        self.active_embargos = [e for e in self.active_embargos if e.end > now]
        
        # Перемещаем начавшиеся из scheduled в active
        started = [e for e in self.scheduled_embargos if e.start <= now <= e.end]
        self.active_embargos.extend(started)
        self.scheduled_embargos = [e for e in self.scheduled_embargos if e.start > now]
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Статистика для мониторинга"""
        now = datetime.now(timezone.utc)
        return {
            "active_embargos": len(self.active_embargos),
            "scheduled_embargos": len(self.scheduled_embargos),
            "next_embargo": self.get_next_embargo(),
            "settings": {
                "fomc_enabled": self.enable_fomc_embargo,
                "weekend_disabled": self.enable_weekend_embargo,
                "volatility_threshold": self.high_volatility_threshold
            }
        }


# === Интеграция с SignalValidator ===
def integrate_with_signal_validator():
    """
    Пример интеграции с существующим SignalValidator
    """
    # В signal_validator.py добавить:
    
    def _validate_embargo_windows(cfg, embargo_manager) -> List[str]:
        reasons = []
        try:
            symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
            is_embargoed, embargo_reasons = embargo_manager.check_embargo_status(symbol)
            
            if is_embargoed:
                reasons.extend([f"embargo:{r}" for r in embargo_reasons])
                logger.warning(f"🚫 Trading embargoed: {embargo_reasons}")
                
        except Exception as e:
            logger.error(f"❌ Embargo check failed: {e}")
            
        return reasons


# === Интеграция с TradingBot ===
def integrate_with_trading_bot():
    """
    Пример интеграции с TradingBot
    """
    # В TradingBot.__init__ добавить:
    # self.embargo_manager = EmbargoManager(self.cfg)
    
    # В TradingBot._tick() в начале добавить:
    def _check_embargo_before_trading(self):
        is_embargoed, reasons = self.embargo_manager.check_embargo_status(self.cfg.SYMBOL)
        if is_embargoed:
            self._notify(f"🚫 Trading embargoed: {', '.join(reasons)}")
            return False
        return True


__all__ = ["EmbargoManager", "EmbargoWindow", "EmbargoReason"]