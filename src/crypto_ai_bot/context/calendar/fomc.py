# fomc.py - FOMC events tracker
"""
📅 FOMC Events Tracker - отслеживание событий Федеральной резервной системы

Интеграция с crypto_ai_bot:
- Автоматическое планирование embargo windows
- Уведомления в Telegram перед событиями
- Влияние на score fusion (снижение весов перед событиями)
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FOMCEventType(Enum):
    """Типы событий FOMC"""
    RATE_DECISION = "rate_decision"          # Решение по ставке
    PRESS_CONFERENCE = "press_conference"     # Пресс-конференция Powell
    MINUTES_RELEASE = "minutes_release"       # Выход протоколов
    SPEECH = "speech"                        # Выступления членов ФРС
    BEIGE_BOOK = "beige_book"               # Бежевая книга
    ECONOMIC_PROJECTIONS = "economic_projections"  # Экономические прогнозы


@dataclass
class FOMCEvent:
    """Событие FOMC"""
    datetime: datetime
    event_type: FOMCEventType
    title: str
    description: str
    impact_level: str = "HIGH"  # LOW, MEDIUM, HIGH, CRITICAL
    speaker: Optional[str] = None
    expected_rate: Optional[float] = None
    previous_rate: Optional[float] = None
    
    def time_until_event(self, timestamp: Optional[datetime] = None) -> float:
        """Минуты до события"""
        now = timestamp or datetime.now(timezone.utc)
        return (self.datetime - now).total_seconds() / 60.0
    
    def is_upcoming(self, hours_ahead: int = 24) -> bool:
        """Проверка, предстоит ли событие в ближайшие N часов"""
        return 0 <= self.time_until_event() <= hours_ahead * 60


class FOMCTracker:
    """
    Трекер событий FOMC с интеграцией в торговую систему
    
    Возможности:
    - Статический календарь + динамическое обновление
    - Автоматические embargo windows
    - Уведомления перед событиями
    - Влияние на торговые решения
    """
    
    def __init__(self, settings: Optional[Any] = None, embargo_manager=None, notifier=None):
        self.settings = settings
        self.embargo_manager = embargo_manager
        self.notifier = notifier
        
        # Настройки
        self.enable_fomc_tracking = getattr(settings, "ENABLE_FOMC_TRACKING", True)
        self.notification_hours_ahead = getattr(settings, "FOMC_NOTIFICATION_HOURS", [24, 4, 1])
        self.impact_score_reduction = getattr(settings, "FOMC_SCORE_REDUCTION", 0.15)
        
        # События
        self.events: List[FOMCEvent] = []
        self.notified_events: set = set()  # Избежать дублирования уведомлений
        
        # Загружаем статический календарь
        self._load_fomc_calendar_2025()
        
        logger.info(f"📅 FOMC Tracker initialized: {len(self.events)} events loaded")
    
    # === Основной API ===
    def get_next_event(self, event_types: Optional[List[FOMCEventType]] = None) -> Optional[FOMCEvent]:
        """Получить следующее событие FOMC"""
        now = datetime.now(timezone.utc)
        upcoming = [e for e in self.events if e.datetime > now]
        
        if event_types:
            upcoming = [e for e in upcoming if e.event_type in event_types]
            
        return min(upcoming, key=lambda x: x.datetime) if upcoming else None
    
    def get_upcoming_events(self, hours_ahead: int = 48) -> List[FOMCEvent]:
        """Получить события в ближайшие N часов"""
        return [e for e in self.events if e.is_upcoming(hours_ahead)]
    
    def is_fomc_impact_period(self, timestamp: Optional[datetime] = None,
                             hours_before: int = 4, hours_after: int = 2) -> Tuple[bool, Optional[FOMCEvent]]:
        """
        Проверка периода влияния FOMC на рынки
        
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
        Корректировка торговых скоров перед FOMC событиями
        
        Returns:
            (adjusted_score, reason)
        """
        is_impact, event = self.is_fomc_impact_period(timestamp)
        
        if not is_impact or not event:
            return base_score, "no_fomc_impact"
            
        # Снижаем score в зависимости от важности события
        impact_multipliers = {
            "LOW": 0.95,
            "MEDIUM": 0.90,
            "HIGH": 0.85,
            "CRITICAL": 0.75
        }
        
        multiplier = impact_multipliers.get(event.impact_level, 0.85)
        adjusted = base_score * multiplier
        
        reason = f"fomc_{event.event_type.value}_{event.impact_level.lower()}"
        
        logger.info(f"📅 FOMC score adjustment: {base_score:.3f} → {adjusted:.3f} ({reason})")
        return adjusted, reason
    
    # === Интеграция с системой ===
    def process_notifications(self):
        """Обработка уведомлений о предстоящих событиях"""
        if not self.notifier:
            return
            
        for hours in self.notification_hours_ahead:
            upcoming = [e for e in self.events 
                       if 0 <= e.time_until_event() <= hours * 60 + 5]  # +5 мин погрешность
            
            for event in upcoming:
                event_key = f"{event.datetime.isoformat()}_{hours}h"
                
                if event_key not in self.notified_events:
                    self._send_fomc_notification(event, hours)
                    self.notified_events.add(event_key)
    
    def schedule_embargo_windows(self):
        """Планирование торговых ограничений"""
        if not self.embargo_manager:
            return
            
        high_impact_events = [e for e in self.events 
                             if e.event_type in [FOMCEventType.RATE_DECISION, 
                                               FOMCEventType.PRESS_CONFERENCE]]
        
        for event in high_impact_events:
            if event.time_until_event() > 0:  # Только будущие события
                self.embargo_manager.schedule_fomc_embargo(
                    event.datetime, 
                    f"{event.title} ({event.impact_level})"
                )
    
    # === Статический календарь ===
    def _load_fomc_calendar_2025(self):
        """Загрузка известных дат FOMC на 2025 год"""
        # Официальные даты заседаний FOMC 2025
        fomc_meetings_2025 = [
            # Формат: (дата, время_утc, ожидаемая_ставка)
            ("2025-01-29", "19:00", None),  # Январь
            ("2025-03-19", "19:00", None),  # Март  
            ("2025-04-30", "19:00", None),  # Апрель
            ("2025-06-11", "19:00", None),  # Июнь
            ("2025-07-30", "19:00", None),  # Июль
            ("2025-09-17", "19:00", None),  # Сентябрь
            ("2025-11-05", "19:00", None),  # Ноябрь
            ("2025-12-17", "19:00", None),  # Декабрь
        ]
        
        for date_str, time_str, expected_rate in fomc_meetings_2025:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}+00:00")
            
            # Решение по ставке
            self.events.append(FOMCEvent(
                datetime=dt,
                event_type=FOMCEventType.RATE_DECISION,
                title=f"FOMC Rate Decision - {dt.strftime('%B %Y')}",
                description="Federal Reserve interest rate decision",
                impact_level="CRITICAL",
                expected_rate=expected_rate
            ))
            
            # Пресс-конференция (только на избранных заседаниях)
            if dt.month in [1, 3, 6, 9, 12]:  # Квартальные заседания
                self.events.append(FOMCEvent(
                    datetime=dt + timedelta(minutes=30),
                    event_type=FOMCEventType.PRESS_CONFERENCE,
                    title=f"Powell Press Conference - {dt.strftime('%B %Y')}",
                    description="Federal Reserve Chair press conference",
                    impact_level="HIGH",
                    speaker="Jerome Powell"
                ))
        
        # Протоколы заседаний (выходят через 3 недели)
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
        
        # Сортируем по времени
        self.events.sort(key=lambda x: x.datetime)
    
    def add_custom_event(self, datetime: datetime, event_type: FOMCEventType,
                        title: str, impact_level: str = "MEDIUM"):
        """Добавление кастомного события"""
        event = FOMCEvent(
            datetime=datetime,
            event_type=event_type,
            title=title,
            description=f"Custom {event_type.value}",
            impact_level=impact_level
        )
        
        self.events.append(event)
        self.events.sort(key=lambda x: x.datetime)
        logger.info(f"📅 Added custom FOMC event: {title}")
    
    # === Вспомогательные методы ===
    def _send_fomc_notification(self, event: FOMCEvent, hours_ahead: int):
        """Отправка уведомления о событии"""
        try:
            time_str = event.datetime.strftime("%Y-%m-%d %H:%M UTC")
            message = (
                f"📅 FOMC Alert ({hours_ahead}h ahead)\n"
                f"Event: {event.title}\n"
                f"Time: {time_str}\n"
                f"Impact: {event.impact_level}\n"
                f"Type: {event.event_type.value.replace('_', ' ').title()}"
            )
            
            if event.speaker:
                message += f"\nSpeaker: {event.speaker}"
                
            self.notifier(message)
            logger.info(f"📅 FOMC notification sent: {event.title}")
            
        except Exception as e:
            logger.error(f"❌ FOMC notification failed: {e}")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Статистика для мониторинга"""
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


# === Интеграция с Score Fusion ===
def integrate_with_score_fusion():
    """
    Пример интеграции с системой scoring
    """
    # В score_fusion.py можно добавить:
    
    def apply_fomc_adjustment(rule_score: float, ai_score: float, 
                             fomc_tracker) -> Tuple[float, float, str]:
        """Применение FOMC корректировок к скорам"""
        rule_adj, reason1 = fomc_tracker.get_score_adjustment(rule_score)
        ai_adj, reason2 = fomc_tracker.get_score_adjustment(ai_score) 
        
        reason = f"fomc_adjustment:{reason1}" if reason1 != "no_fomc_impact" else "no_fomc_adjustment"
        return rule_adj, ai_adj, reason


__all__ = ["FOMCTracker", "FOMCEvent", "FOMCEventType"]