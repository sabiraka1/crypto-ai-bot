# embargo_windows.py - РЎРёСЃС‚РµРјР° С‚РѕСЂРіРѕРІС‹С… РѕРіСЂР°РЅРёС‡РµРЅРёР№
"""
рџљ« Trading Embargo Windows - СѓРїСЂР°РІР»РµРЅРёРµ РІСЂРµРјРµРЅРЅС‹РјРё РѕРіСЂР°РЅРёС‡РµРЅРёСЏРјРё С‚РѕСЂРіРѕРІР»Рё

РРЅС‚РµРіСЂР°С†РёСЏ СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµР№ Р°СЂС…РёС‚РµРєС‚СѓСЂРѕР№:
- РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІ SignalValidator РґР»СЏ Р±Р»РѕРєРёСЂРѕРІРєРё СЃРёРіРЅР°Р»РѕРІ
- РРЅС‚РµРіСЂРёСЂСѓРµС‚СЃСЏ СЃ TradingBot С‡РµСЂРµР· РІСЂРµРјРµРЅРЅС‹Рµ РїСЂРѕРІРµСЂРєРё
- РџРѕРґРґРµСЂР¶РёРІР°РµС‚ РЅР°СЃС‚СЂРѕР№РєРё С‡РµСЂРµР· Settings
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EmbargoReason(Enum):
    """РџСЂРёС‡РёРЅС‹ С‚РѕСЂРіРѕРІРѕРіРѕ СЌРјР±Р°СЂРіРѕ"""
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
    """Р’СЂРµРјРµРЅРЅРѕРµ РѕРєРЅРѕ С‚РѕСЂРіРѕРІРѕРіРѕ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ"""
    start: datetime
    end: datetime
    reason: EmbargoReason
    description: str
    severity: str = "BLOCK"  # BLOCK, WARN, REDUCE_SIZE
    affected_symbols: Optional[List[str]] = None  # None = РІСЃРµ СЃРёРјРІРѕР»С‹
    
    def is_active(self, timestamp: Optional[datetime] = None) -> bool:
        """РџСЂРѕРІРµСЂРєР° Р°РєС‚РёРІРЅРѕСЃС‚Рё РѕРєРЅР° РѕРіСЂР°РЅРёС‡РµРЅРёСЏ"""
        now = timestamp or datetime.now(timezone.utc)
        return self.start <= now <= self.end
    
    def time_until_start(self, timestamp: Optional[datetime] = None) -> float:
        """РњРёРЅСѓС‚С‹ РґРѕ РЅР°С‡Р°Р»Р° РѕРіСЂР°РЅРёС‡РµРЅРёСЏ"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.start - now).total_seconds() / 60.0
    
    def time_until_end(self, timestamp: Optional[datetime] = None) -> float:
        """РњРёРЅСѓС‚С‹ РґРѕ РѕРєРѕРЅС‡Р°РЅРёСЏ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.end - now).total_seconds() / 60.0


class EmbargoManager:
    """
    Р¦РµРЅС‚СЂР°Р»СЊРЅС‹Р№ РјРµРЅРµРґР¶РµСЂ С‚РѕСЂРіРѕРІС‹С… РѕРіСЂР°РЅРёС‡РµРЅРёР№
    
    РРЅС‚РµРіСЂР°С†РёСЏ:
    - Р’ _validate_time_windows() SignalValidator
    - Р’ TradingBot._tick() РґР»СЏ РїСЂРѕРІРµСЂРєРё РїРµСЂРµРґ Р°РЅР°Р»РёР·РѕРј
    - Р’ PositionManager РґР»СЏ СЌРєСЃС‚СЂРµРЅРЅРѕРіРѕ Р·Р°РєСЂС‹С‚РёСЏ РїСЂРё РєСЂРёС‚РёС‡РµСЃРєРёС… СЃРѕР±С‹С‚РёСЏС…
    """
    
    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings
        self.active_embargos: List[EmbargoWindow] = []
        self.scheduled_embargos: List[EmbargoWindow] = []
        
        # РќР°СЃС‚СЂРѕР№РєРё РёР· Settings
        self.enable_fomc_embargo = getattr(settings, "ENABLE_FOMC_EMBARGO", True)
        self.enable_weekend_embargo = getattr(settings, "DISABLE_WEEKEND_TRADING", False)
        self.fomc_embargo_minutes = getattr(settings, "FOMC_EMBARGO_MINUTES", 30)
        self.high_volatility_threshold = getattr(settings, "HIGH_VOLATILITY_EMBARGO_THRESHOLD", 8.0)
        
        logger.info(f"рџљ« EmbargoManager initialized: FOMC={self.enable_fomc_embargo}")
    
    # === РћСЃРЅРѕРІРЅРѕР№ API ===
    def check_embargo_status(self, symbol: str = "BTC/USDT", 
                           timestamp: Optional[datetime] = None) -> Tuple[bool, List[str]]:
        """
        Р“Р»Р°РІРЅР°СЏ С„СѓРЅРєС†РёСЏ РїСЂРѕРІРµСЂРєРё С‚РѕСЂРіРѕРІС‹С… РѕРіСЂР°РЅРёС‡РµРЅРёР№
        
        Returns:
            (is_embargoed, reasons) - РјРѕР¶РЅРѕ Р»Рё С‚РѕСЂРіРѕРІР°С‚СЊ Рё РїСЂРёС‡РёРЅС‹ РѕРіСЂР°РЅРёС‡РµРЅРёР№
        """
        now = timestamp or datetime.now(timezone.utc)
        reasons = []
        
        # РџСЂРѕРІРµСЂСЏРµРј Р°РєС‚РёРІРЅС‹Рµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ
        for embargo in self.active_embargos:
            if embargo.is_active(now):
                if not embargo.affected_symbols or symbol in embargo.affected_symbols:
                    if embargo.severity == "BLOCK":
                        reasons.append(f"{embargo.reason.value}: {embargo.description}")
        
        # Р”РёРЅР°РјРёС‡РµСЃРєРёРµ РїСЂРѕРІРµСЂРєРё
        weekend_reason = self._check_weekend_embargo(now)
        if weekend_reason:
            reasons.append(weekend_reason)
            
        return len(reasons) > 0, reasons
    
    def get_next_embargo(self, symbol: str = "BTC/USDT") -> Optional[EmbargoWindow]:
        """РџРѕР»СѓС‡РёС‚СЊ СЃР»РµРґСѓСЋС‰РµРµ Р±Р»РёР¶Р°Р№С€РµРµ РѕРіСЂР°РЅРёС‡РµРЅРёРµ"""
        now = datetime.now(timezone.utc)
        upcoming = [e for e in self.scheduled_embargos 
                   if e.start > now and (not e.affected_symbols or symbol in e.affected_symbols)]
        return min(upcoming, key=lambda x: x.start) if upcoming else None
    
    # === РРЅС‚РµРіСЂР°С†РёСЏ СЃ FOMC ===
    def schedule_fomc_embargo(self, fomc_datetime: datetime, description: str = "FOMC Meeting"):
        """РџР»Р°РЅРёСЂРѕРІР°РЅРёРµ РѕРіСЂР°РЅРёС‡РµРЅРёР№ РІРѕРєСЂСѓРі СЃРѕР±С‹С‚РёР№ FOMC"""
        if not self.enable_fomc_embargo:
            return
            
        # РћРіСЂР°РЅРёС‡РµРЅРёРµ Р·Р° 30 РјРёРЅСѓС‚ РґРѕ Рё 15 РјРёРЅСѓС‚ РїРѕСЃР»Рµ
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
        logger.info(f"рџ“… FOMC embargo scheduled: {start} - {end}")
    
    # === Р”РёРЅР°РјРёС‡РµСЃРєРёРµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ ===
    def trigger_volatility_embargo(self, atr_pct: float, duration_minutes: int = 15):
        """Р­РєСЃС‚СЂРµРЅРЅРѕРµ РѕРіСЂР°РЅРёС‡РµРЅРёРµ РїСЂРё РІС‹СЃРѕРєРѕР№ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё"""
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
        logger.warning(f"рџЊЄпёЏ Volatility embargo triggered: ATR {atr_pct:.2f}%")
    
    def add_manual_embargo(self, minutes: int, reason: str):
        """Р СѓС‡РЅРѕРµ РѕРіСЂР°РЅРёС‡РµРЅРёРµ С‚РѕСЂРіРѕРІР»Рё"""
        now = datetime.now(timezone.utc)
        embargo = EmbargoWindow(
            start=now,
            end=now + timedelta(minutes=minutes),
            reason=EmbargoReason.MANUAL_OVERRIDE,
            description=f"Manual: {reason}",
            severity="BLOCK"
        )
        
        self.active_embargos.append(embargo)
        logger.warning(f"вњ‹ Manual embargo: {minutes}min - {reason}")
    
    # === Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ РјРµС‚РѕРґС‹ ===
    def _check_weekend_embargo(self, timestamp: datetime) -> Optional[str]:
        """РџСЂРѕРІРµСЂРєР° РІС‹С…РѕРґРЅС‹С… РґРЅРµР№"""
        if not self.enable_weekend_embargo:
            return None
            
        if timestamp.weekday() >= 5:  # РЎСѓР±Р±РѕС‚Р°/Р’РѕСЃРєСЂРµСЃРµРЅСЊРµ
            return f"weekend_trading_disabled: {timestamp.strftime('%A')}"
        return None
    
    def cleanup_expired_embargos(self):
        """РћС‡РёСЃС‚РєР° РёСЃС‚РµРєС€РёС… РѕРіСЂР°РЅРёС‡РµРЅРёР№"""
        now = datetime.now(timezone.utc)
        
        # РЈРґР°Р»СЏРµРј РёСЃС‚РµРєС€РёРµ Р°РєС‚РёРІРЅС‹Рµ
        self.active_embargos = [e for e in self.active_embargos if e.end > now]
        
        # РџРµСЂРµРјРµС‰Р°РµРј РЅР°С‡Р°РІС€РёРµСЃСЏ РёР· scheduled РІ active
        started = [e for e in self.scheduled_embargos if e.start <= now <= e.end]
        self.active_embargos.extend(started)
        self.scheduled_embargos = [e for e in self.scheduled_embargos if e.start > now]
    
    def get_status_summary(self) -> Dict[str, Any]:
        """РЎС‚Р°С‚РёСЃС‚РёРєР° РґР»СЏ РјРѕРЅРёС‚РѕСЂРёРЅРіР°"""
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


# === РРЅС‚РµРіСЂР°С†РёСЏ СЃ SignalValidator ===
def integrate_with_signal_validator():
    """
    РџСЂРёРјРµСЂ РёРЅС‚РµРіСЂР°С†РёРё СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРј SignalValidator
    """
    # Р’ signal_validator.py РґРѕР±Р°РІРёС‚СЊ:
    
    def _validate_embargo_windows(cfg, embargo_manager) -> List[str]:
        reasons = []
        try:
            symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
            is_embargoed, embargo_reasons = embargo_manager.check_embargo_status(symbol)
            
            if is_embargoed:
                reasons.extend([f"embargo:{r}" for r in embargo_reasons])
                logger.warning(f"рџљ« Trading embargoed: {embargo_reasons}")
                
        except Exception as e:
            logger.error(f"вќЊ Embargo check failed: {e}")
            
        return reasons


# === РРЅС‚РµРіСЂР°С†РёСЏ СЃ TradingBot ===
def integrate_with_trading_bot():
    """
    РџСЂРёРјРµСЂ РёРЅС‚РµРіСЂР°С†РёРё СЃ TradingBot
    """
    # Р’ TradingBot.__init__ РґРѕР±Р°РІРёС‚СЊ:
    # self.embargo_manager = EmbargoManager(self.cfg)
    
    # Р’ TradingBot._tick() РІ РЅР°С‡Р°Р»Рµ РґРѕР±Р°РІРёС‚СЊ:
    def _check_embargo_before_trading(self):
        is_embargoed, reasons = self.embargo_manager.check_embargo_status(self.cfg.SYMBOL)
        if is_embargoed:
            self._notify(f"рџљ« Trading embargoed: {', '.join(reasons)}")
            return False
        return True


__all__ = ["EmbargoManager", "EmbargoWindow", "EmbargoReason"]










