# fomc.py - FOMC events tracker
"""
рџ“… FOMC Events Tracker - РѕС‚СЃР»РµР¶РёРІР°РЅРёРµ СЃРѕР±С‹С‚РёР№ Р¤РµРґРµСЂР°Р»СЊРЅРѕР№ СЂРµР·РµСЂРІРЅРѕР№ СЃРёСЃС‚РµРјС‹

РРЅС‚РµРіСЂР°С†РёСЏ СЃ crypto_ai_bot:
- РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРµ РїР»Р°РЅРёСЂРѕРІР°РЅРёРµ embargo windows
- РЈРІРµРґРѕРјР»РµРЅРёСЏ РІ Telegram РїРµСЂРµРґ СЃРѕР±С‹С‚РёСЏРјРё
- Р’Р»РёСЏРЅРёРµ РЅР° score fusion (СЃРЅРёР¶РµРЅРёРµ РІРµСЃРѕРІ РїРµСЂРµРґ СЃРѕР±С‹С‚РёСЏРјРё)
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FOMCEventType(Enum):
    """РўРёРїС‹ СЃРѕР±С‹С‚РёР№ FOMC"""
    RATE_DECISION = "rate_decision"          # Р РµС€РµРЅРёРµ РїРѕ СЃС‚Р°РІРєРµ
    PRESS_CONFERENCE = "press_conference"     # РџСЂРµСЃСЃ-РєРѕРЅС„РµСЂРµРЅС†РёСЏ Powell
    MINUTES_RELEASE = "minutes_release"       # Р’С‹С…РѕРґ РїСЂРѕС‚РѕРєРѕР»РѕРІ
    SPEECH = "speech"                        # Р’С‹СЃС‚СѓРїР»РµРЅРёСЏ С‡Р»РµРЅРѕРІ Р¤Р РЎ
    BEIGE_BOOK = "beige_book"               # Р‘РµР¶РµРІР°СЏ РєРЅРёРіР°
    ECONOMIC_PROJECTIONS = "economic_projections"  # Р­РєРѕРЅРѕРјРёС‡РµСЃРєРёРµ РїСЂРѕРіРЅРѕР·С‹


@dataclass
class FOMCEvent:
    """РЎРѕР±С‹С‚РёРµ FOMC"""
    datetime: datetime
    event_type: FOMCEventType
    title: str
    description: str
    impact_level: str = "HIGH"  # LOW, MEDIUM, HIGH, CRITICAL
    speaker: Optional[str] = None
    expected_rate: Optional[float] = None
    previous_rate: Optional[float] = None
    
    def time_until_event(self, timestamp: Optional[datetime] = None) -> float:
        """РњРёРЅСѓС‚С‹ РґРѕ СЃРѕР±С‹С‚РёСЏ"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.datetime - now).total_seconds() / 60.0
    
    def is_upcoming(self, hours_ahead: int = 24) -> bool:
        """РџСЂРѕРІРµСЂРєР°, РїСЂРµРґСЃС‚РѕРёС‚ Р»Рё СЃРѕР±С‹С‚РёРµ РІ Р±Р»РёР¶Р°Р№С€РёРµ N С‡Р°СЃРѕРІ"""
        return 0 <= self.time_until_event() <= hours_ahead * 60


class FOMCTracker:
    """
    РўСЂРµРєРµСЂ СЃРѕР±С‹С‚РёР№ FOMC СЃ РёРЅС‚РµРіСЂР°С†РёРµР№ РІ С‚РѕСЂРіРѕРІСѓСЋ СЃРёСЃС‚РµРјСѓ
    
    Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё:
    - РЎС‚Р°С‚РёС‡РµСЃРєРёР№ РєР°Р»РµРЅРґР°СЂСЊ + РґРёРЅР°РјРёС‡РµСЃРєРѕРµ РѕР±РЅРѕРІР»РµРЅРёРµ
    - РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРёРµ embargo windows
    - РЈРІРµРґРѕРјР»РµРЅРёСЏ РїРµСЂРµРґ СЃРѕР±С‹С‚РёСЏРјРё
    - Р’Р»РёСЏРЅРёРµ РЅР° С‚РѕСЂРіРѕРІС‹Рµ СЂРµС€РµРЅРёСЏ
    """
    
    def __init__(self, settings: Optional[Any] = None, embargo_manager=None, notifier=None):
        self.settings = settings
        self.embargo_manager = embargo_manager
        self.notifier = notifier
        
        # РќР°СЃС‚СЂРѕР№РєРё
        self.enable_fomc_tracking = getattr(settings, "ENABLE_FOMC_TRACKING", True)
        self.notification_hours_ahead = getattr(settings, "FOMC_NOTIFICATION_HOURS", [24, 4, 1])
        self.impact_score_reduction = getattr(settings, "FOMC_SCORE_REDUCTION", 0.15)
        
        # РЎРѕР±С‹С‚РёСЏ
        self.events: List[FOMCEvent] = []
        self.notified_events: set = set()  # РР·Р±РµР¶Р°С‚СЊ РґСѓР±Р»РёСЂРѕРІР°РЅРёСЏ СѓРІРµРґРѕРјР»РµРЅРёР№
        
        # Р—Р°РіСЂСѓР¶Р°РµРј СЃС‚Р°С‚РёС‡РµСЃРєРёР№ РєР°Р»РµРЅРґР°СЂСЊ
        self._load_fomc_calendar_2025()
        
        logger.info(f"рџ“… FOMC Tracker initialized: {len(self.events)} events loaded")
    
    # === РћСЃРЅРѕРІРЅРѕР№ API ===
    def get_next_event(self, event_types: Optional[List[FOMCEventType]] = None) -> Optional[FOMCEvent]:
        """РџРѕР»СѓС‡РёС‚СЊ СЃР»РµРґСѓСЋС‰РµРµ СЃРѕР±С‹С‚РёРµ FOMC"""
        now = datetime.now(timezone.utc)
        upcoming = [e for e in self.events if e.datetime > now]
        
        if event_types:
            upcoming = [e for e in upcoming if e.event_type in event_types]
            
        return min(upcoming, key=lambda x: x.datetime) if upcoming else None
    
    def get_upcoming_events(self, hours_ahead: int = 48) -> List[FOMCEvent]:
        """РџРѕР»СѓС‡РёС‚СЊ СЃРѕР±С‹С‚РёСЏ РІ Р±Р»РёР¶Р°Р№С€РёРµ N С‡Р°СЃРѕРІ"""
        return [e for e in self.events if e.is_upcoming(hours_ahead)]
    
    def is_fomc_impact_period(self, timestamp: Optional[datetime] = None,
                             hours_before: int = 4, hours_after: int = 2) -> Tuple[bool, Optional[FOMCEvent]]:
        """
        РџСЂРѕРІРµСЂРєР° РїРµСЂРёРѕРґР° РІР»РёСЏРЅРёСЏ FOMC РЅР° СЂС‹РЅРєРё
        
        Returns:
            (is_impact_period, closest_event)
        """
        now = timestamp or datetime.now(timezone.utc)
        
        for event in self.events:
            start_impact = event.datetime - timedelta(hours=hours_before)
            end_impact = event.datetime + timedelta(hours=hours_after)
            
            if start_impact <= now <= end_impact:
                return True, event
                
        return False, None
    
    def get_score_adjustment(self, base_score: float, 
                           timestamp: Optional[datetime] = None) -> Tuple[float, str]:
        """
        РљРѕСЂСЂРµРєС‚РёСЂРѕРІРєР° С‚РѕСЂРіРѕРІС‹С… СЃРєРѕСЂРѕРІ РїРµСЂРµРґ FOMC СЃРѕР±С‹С‚РёСЏРјРё
        
        Returns:
            (adjusted_score, reason)
        """
        is_impact, event = self.is_fomc_impact_period(timestamp)
        
        if not is_impact or not event:
            return base_score, "no_fomc_impact"
            
        # РЎРЅРёР¶Р°РµРј score РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ РІР°Р¶РЅРѕСЃС‚Рё СЃРѕР±С‹С‚РёСЏ
        impact_multipliers = {
            "LOW": 0.95,
            "MEDIUM": 0.90,
            "HIGH": 0.85,
            "CRITICAL": 0.75
        }
        
        multiplier = impact_multipliers.get(event.impact_level, 0.85)
        adjusted = base_score * multiplier
        
        reason = f"fomc_{event.event_type.value}_{event.impact_level.lower()}"
        
        logger.info(f"рџ“… FOMC score adjustment: {base_score:.3f} в†’ {adjusted:.3f} ({reason})")
        return adjusted, reason
    
    # === РРЅС‚РµРіСЂР°С†РёСЏ СЃ СЃРёСЃС‚РµРјРѕР№ ===
    def process_notifications(self):
        """РћР±СЂР°Р±РѕС‚РєР° СѓРІРµРґРѕРјР»РµРЅРёР№ Рѕ РїСЂРµРґСЃС‚РѕСЏС‰РёС… СЃРѕР±С‹С‚РёСЏС…"""
        if not self.notifier:
            return
            
        for hours in self.notification_hours_ahead:
            upcoming = [e for e in self.events 
                       if 0 <= e.time_until_event() <= hours * 60 + 5]  # +5 РјРёРЅ РїРѕРіСЂРµС€РЅРѕСЃС‚СЊ
            
            for event in upcoming:
                event_key = f"{event.datetime.isoformat()}_{hours}h"
                
                if event_key not in self.notified_events:
                    self._send_fomc_notification(event, hours)
                    self.notified_events.add(event_key)
    
    def schedule_embargo_windows(self):
        """РџР»Р°РЅРёСЂРѕРІР°РЅРёРµ С‚РѕСЂРіРѕРІС‹С… РѕРіСЂР°РЅРёС‡РµРЅРёР№"""
        if not self.embargo_manager:
            return
            
        high_impact_events = [e for e in self.events 
                             if e.event_type in [FOMCEventType.RATE_DECISION, 
                                               FOMCEventType.PRESS_CONFERENCE]]
        
        for event in high_impact_events:
            if event.time_until_event() > 0:  # РўРѕР»СЊРєРѕ Р±СѓРґСѓС‰РёРµ СЃРѕР±С‹С‚РёСЏ
                self.embargo_manager.schedule_fomc_embargo(
                    event.datetime, 
                    f"{event.title} ({event.impact_level})"
                )
    
    # === РЎС‚Р°С‚РёС‡РµСЃРєРёР№ РєР°Р»РµРЅРґР°СЂСЊ ===
    def _load_fomc_calendar_2025(self):
        """Р—Р°РіСЂСѓР·РєР° РёР·РІРµСЃС‚РЅС‹С… РґР°С‚ FOMC РЅР° 2025 РіРѕРґ"""
        # РћС„РёС†РёР°Р»СЊРЅС‹Рµ РґР°С‚С‹ Р·Р°СЃРµРґР°РЅРёР№ FOMC 2025
        fomc_meetings_2025 = [
            # Р¤РѕСЂРјР°С‚: (РґР°С‚Р°, РІСЂРµРјСЏ_СѓС‚c, РѕР¶РёРґР°РµРјР°СЏ_СЃС‚Р°РІРєР°)
            ("2025-01-29", "19:00", None),  # РЇРЅРІР°СЂСЊ
            ("2025-03-19", "19:00", None),  # РњР°СЂС‚  
            ("2025-04-30", "19:00", None),  # РђРїСЂРµР»СЊ
            ("2025-06-11", "19:00", None),  # РСЋРЅСЊ
            ("2025-07-30", "19:00", None),  # РСЋР»СЊ
            ("2025-09-17", "19:00", None),  # РЎРµРЅС‚СЏР±СЂСЊ
            ("2025-11-05", "19:00", None),  # РќРѕСЏР±СЂСЊ
            ("2025-12-17", "19:00", None),  # Р”РµРєР°Р±СЂСЊ
        ]
        
        for date_str, time_str, expected_rate in fomc_meetings_2025:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}+00:00")
            
            # Р РµС€РµРЅРёРµ РїРѕ СЃС‚Р°РІРєРµ
            self.events.append(FOMCEvent(
                datetime=dt,
                event_type=FOMCEventType.RATE_DECISION,
                title=f"FOMC Rate Decision - {dt.strftime('%B %Y')}",
                description="Federal Reserve interest rate decision",
                impact_level="CRITICAL",
                expected_rate=expected_rate
            ))
            
            # РџСЂРµСЃСЃ-РєРѕРЅС„РµСЂРµРЅС†РёСЏ (С‚РѕР»СЊРєРѕ РЅР° РёР·Р±СЂР°РЅРЅС‹С… Р·Р°СЃРµРґР°РЅРёСЏС…)
            if dt.month in [1, 3, 6, 9, 12]:  # РљРІР°СЂС‚Р°Р»СЊРЅС‹Рµ Р·Р°СЃРµРґР°РЅРёСЏ
                self.events.append(FOMCEvent(
                    datetime=dt + timedelta(minutes=30),
                    event_type=FOMCEventType.PRESS_CONFERENCE,
                    title=f"Powell Press Conference - {dt.strftime('%B %Y')}",
                    description="Federal Reserve Chair press conference",
                    impact_level="HIGH",
                    speaker="Jerome Powell"
                ))
        
        # РџСЂРѕС‚РѕРєРѕР»С‹ Р·Р°СЃРµРґР°РЅРёР№ (РІС‹С…РѕРґСЏС‚ С‡РµСЂРµР· 3 РЅРµРґРµР»Рё)
        for event in self.events:
            if event.event_type == FOMCEventType.RATE_DECISION:
                minutes_date = event.datetime + timedelta(weeks=3)
                self.events.append(FOMCEvent(
                    datetime=minutes_date.replace(hour=19, minute=0),  # 2PM ET
                    event_type=FOMCEventType.MINUTES_RELEASE,
                    title=f"FOMC Minutes - {event.datetime.strftime('%B %Y')}",
                    description="Federal Reserve meeting minutes release",
                    impact_level="MEDIUM"
                ))
        
        # РЎРѕСЂС‚РёСЂСѓРµРј РїРѕ РІСЂРµРјРµРЅРё
        self.events.sort(key=lambda x: x.datetime)
    
    def add_custom_event(self, datetime: datetime, event_type: FOMCEventType,
                        title: str, impact_level: str = "MEDIUM"):
        """Р”РѕР±Р°РІР»РµРЅРёРµ РєР°СЃС‚РѕРјРЅРѕРіРѕ СЃРѕР±С‹С‚РёСЏ"""
        event = FOMCEvent(
            datetime=datetime,
            event_type=event_type,
            title=title,
            description=f"Custom {event_type.value}",
            impact_level=impact_level
        )
        
        self.events.append(event)
        self.events.sort(key=lambda x: x.datetime)
        logger.info(f"рџ“… Added custom FOMC event: {title}")
    
    # === Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Рµ РјРµС‚РѕРґС‹ ===
    def _send_fomc_notification(self, event: FOMCEvent, hours_ahead: int):
        """РћС‚РїСЂР°РІРєР° СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ СЃРѕР±С‹С‚РёРё"""
        try:
            time_str = event.datetime.strftime("%Y-%m-%d %H:%M UTC")
            message = (
                f"рџ“… FOMC Alert ({hours_ahead}h ahead)\n"
                f"Event: {event.title}\n"
                f"Time: {time_str}\n"
                f"Impact: {event.impact_level}\n"
                f"Type: {event.event_type.value.replace('_', ' ').title()}"
            )
            
            if event.speaker:
                message += f"\nSpeaker: {event.speaker}"
                
            self.notifier(message)
            logger.info(f"рџ“… FOMC notification sent: {event.title}")
            
        except Exception as e:
            logger.error(f"вќЊ FOMC notification failed: {e}")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """РЎС‚Р°С‚РёСЃС‚РёРєР° РґР»СЏ РјРѕРЅРёС‚РѕСЂРёРЅРіР°"""
        next_event = self.get_next_event()
        upcoming = self.get_upcoming_events(48)
        is_impact, impact_event = self.is_fomc_impact_period()
        
        return {
            "total_events": len(self.events),
            "next_event": {
                "title": next_event.title if next_event else None,
                "datetime": next_event.datetime.isoformat() if next_event else None,
                "hours_until": next_event.time_until_event() / 60 if next_event else None
            },
            "upcoming_48h": len(upcoming),
            "impact_period": {
                "active": is_impact,
                "event": impact_event.title if impact_event else None
            },
            "settings": {
                "tracking_enabled": self.enable_fomc_tracking,
                "notification_hours": self.notification_hours_ahead
            }
        }


# === РРЅС‚РµРіСЂР°С†РёСЏ СЃ Score Fusion ===
def integrate_with_score_fusion():
    """
    РџСЂРёРјРµСЂ РёРЅС‚РµРіСЂР°С†РёРё СЃ СЃРёСЃС‚РµРјРѕР№ scoring
    """
    # Р’ score_fusion.py РјРѕР¶РЅРѕ РґРѕР±Р°РІРёС‚СЊ:
    
    def apply_fomc_adjustment(rule_score: float, ai_score: float, 
                             fomc_tracker) -> Tuple[float, float, str]:
        """РџСЂРёРјРµРЅРµРЅРёРµ FOMC РєРѕСЂСЂРµРєС‚РёСЂРѕРІРѕРє Рє СЃРєРѕСЂР°Рј"""
        rule_adj, reason1 = fomc_tracker.get_score_adjustment(rule_score)
        ai_adj, reason2 = fomc_tracker.get_score_adjustment(ai_score) 
        
        reason = f"fomc_adjustment:{reason1}" if reason1 != "no_fomc_impact" else "no_fomc_adjustment"
        return rule_adj, ai_adj, reason


__all__ = ["FOMCTracker", "FOMCEvent", "FOMCEventType"]










