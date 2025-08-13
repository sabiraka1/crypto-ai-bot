"""
📡 EventBus - Production-ready event system
Потокобезопасная событийная шина с on/emit алиасами и одноразовыми подписками.
"""

import logging
import threading
from collections import defaultdict
from typing import Callable, Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventBus:
    """
    🎯 Простая и надежная событийная шина

    Поддерживает два стиля API:
    - subscribe/publish (основной)
    - on/emit (алиасы для совместимости)

    Features:
    - Thread-safe операции
    - Graceful error handling
    - Не падает при ошибках в handlers
    """

    def __init__(self):
        self._subs: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        logger.debug("📡 EventBus initialized")

    # ── Основной API ─────────────────────────────────────────────────────────
    def subscribe(self, name: str, fn: Callable[[Any], None]) -> None:
        """
        📥 Подписаться на событие

        Args:
            name: Имя события (например, "trade_opened")
            fn: Функция-обработчик, принимающая payload
        """
        if not callable(fn):
            raise TypeError(f"Handler must be callable, got {type(fn)}")

        with self._lock:
            self._subs[name].append(fn)

        logger.debug(f"📥 Subscribed to '{name}', total handlers: {len(self._subs[name])}")

    def publish(self, name: str, payload: Any = None) -> None:
        """
        📤 Опубликовать событие

        Args:
            name: Имя события
            payload: Данные для передачи обработчикам
        """
        # Получаем копию подписчиков под блокировкой
        with self._lock:
            subscribers = self._subs.get(name, []).copy()

        if not subscribers:
            logger.debug(f"📤 No subscribers for event '{name}'")
            return

        logger.debug(f"📤 Publishing '{name}' to {len(subscribers)} handlers")

        # Вызываем обработчики БЕЗ блокировки для избежания deadlock
        failed_count = 0
        for fn in subscribers:
            try:
                fn(payload)
            except Exception as e:
                failed_count += 1
                handler_name = getattr(fn, "__name__", fn.__class__.__name__)
                logger.error(
                    f"❌ Event '{name}' handler {handler_name} failed: {e}",
                    exc_info=True
                )

        if failed_count > 0:
            logger.warning(f"⚠️ Event '{name}': {failed_count}/{len(subscribers)} handlers failed")

    def unsubscribe(self, name: str, fn: Callable[[Any], None]) -> bool:
        """
        📤 Отписаться от события

        Returns:
            True если обработчик был найден и удален
        """
        with self._lock:
            if name in self._subs and fn in self._subs[name]:
                self._subs[name].remove(fn)
                logger.debug(f"📤 Unsubscribed from '{name}', remaining: {len(self._subs[name])}")
                return True

        logger.debug(f"📤 Handler not found for '{name}'")
        return False

    # ── Одноразовая подписка ─────────────────────────────────────────────────
    def subscribe_once(self, name: str, fn: Callable[[Any], None]) -> None:
        """
        📥 Подписаться на событие один раз: после первого вызова обработчик удаляется.
        """
        def wrapper(payload):
            try:
                fn(payload)
            finally:
                # важно: отписываем именно wrapper
                self.unsubscribe(name, wrapper)

        self.subscribe(name, wrapper)

    # Алиас
    def once(self, name: str, fn: Callable[[Any], None]) -> None:
        self.subscribe_once(name, fn)

    # ── Алиасы для совместимости с on/emit стилем ────────────────────────────
    def on(self, name: str, fn: Callable[[Any], None]) -> None:
        self.subscribe(name, fn)

    def emit(self, name: str, payload: Any = None) -> None:
        self.publish(name, payload)

    def off(self, name: str, fn: Callable[[Any], None]) -> bool:
        return self.unsubscribe(name, fn)

    # ── Утилиты ──────────────────────────────────────────────────────────────
    def clear_event(self, name: str) -> int:
        """
        🗑️ Удалить всех подписчиков события

        Returns:
            Количество удаленных обработчиков
        """
        with self._lock:
            count = len(self._subs.get(name, []))
            if name in self._subs:
                del self._subs[name]

        logger.debug(f"🗑️ Cleared event '{name}', removed {count} handlers")
        return count

    def clear_all(self) -> int:
        """
        🗑️ Удалить ВСЕ подписки

        Returns:
            Общее количество удаленных обработчиков
        """
        with self._lock:
            total_count = sum(len(handlers) for handlers in self._subs.values())
            self._subs.clear()

        logger.debug(f"🗑️ Cleared all events, removed {total_count} handlers")
        return total_count

    def list_events(self) -> Dict[str, int]:
        """
        📋 Получить список всех событий и количество подписчиков

        Returns:
            Dict с событиями и количеством обработчиков
        """
        with self._lock:
            return {evt: len(handlers) for evt, handlers in self._subs.items()}

    def has_subscribers(self, name: str) -> bool:
        """
        ❓ Проверить есть ли подписчики на событие

        Returns:
            True если есть подписчики
        """
        with self._lock:
            return len(self._subs.get(name, [])) > 0

    # ── Debugging и статистика ───────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        """📊 Получить статистику EventBus"""
        with self._lock:
            events = {k: v.copy() for k, v in self._subs.items()}

        return {
            "total_events": len(events),
            "total_handlers": sum(len(handlers) for handlers in events.values()),
            "events": {name: len(handlers) for name, handlers in events.items()},
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return f"EventBus(events={stats['total_events']}, handlers={stats['total_handlers']})"


# ── Глобальный instance (опционально) ────────────────────────────────────────
_global_eventbus: Optional[EventBus] = None


def get_global_eventbus() -> EventBus:
    """🌐 Получить глобальный EventBus (создается при первом вызове)"""
    global _global_eventbus
    if _global_eventbus is None:
        _global_eventbus = EventBus()
        logger.info("🌐 Global EventBus created")
    return _global_eventbus


def set_global_eventbus(eventbus: EventBus) -> None:
    """🌐 Установить глобальный EventBus"""
    global _global_eventbus
    _global_eventbus = eventbus
    logger.info("🌐 Global EventBus set")


__all__ = ["EventBus", "get_global_eventbus", "set_global_eventbus"]
