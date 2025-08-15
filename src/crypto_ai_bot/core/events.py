"""
рџ“Ў EventBus - Production-ready event system
РџРѕС‚РѕРєРѕР±РµР·РѕРїР°СЃРЅР°СЏ СЃРѕР±С‹С‚РёР№РЅР°СЏ С€РёРЅР° СЃ on/emit Р°Р»РёР°СЃР°РјРё Рё РѕРґРЅРѕСЂР°Р·РѕРІС‹РјРё РїРѕРґРїРёСЃРєР°РјРё.
"""

import logging
import threading
from collections import defaultdict
from typing import Callable, Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventBus:
    """
    рџЋЇ РџСЂРѕСЃС‚Р°СЏ Рё РЅР°РґРµР¶РЅР°СЏ СЃРѕР±С‹С‚РёР№РЅР°СЏ С€РёРЅР°

    РџРѕРґРґРµСЂР¶РёРІР°РµС‚ РґРІР° СЃС‚РёР»СЏ API:
    - subscribe/publish (РѕСЃРЅРѕРІРЅРѕР№)
    - on/emit (Р°Р»РёР°СЃС‹ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё)

    Features:
    - Thread-safe РѕРїРµСЂР°С†РёРё
    - Graceful error handling
    - РќРµ РїР°РґР°РµС‚ РїСЂРё РѕС€РёР±РєР°С… РІ handlers
    """

    def __init__(self):
        self._subs: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        logger.debug("рџ“Ў EventBus initialized")

    # в”Ђв”Ђ РћСЃРЅРѕРІРЅРѕР№ API в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def subscribe(self, name: str, fn: Callable[[Any], None]) -> None:
        """
        рџ“Ґ РџРѕРґРїРёСЃР°С‚СЊСЃСЏ РЅР° СЃРѕР±С‹С‚РёРµ

        Args:
            name: РРјСЏ СЃРѕР±С‹С‚РёСЏ (РЅР°РїСЂРёРјРµСЂ, "trade_opened")
            fn: Р¤СѓРЅРєС†РёСЏ-РѕР±СЂР°Р±РѕС‚С‡РёРє, РїСЂРёРЅРёРјР°СЋС‰Р°СЏ payload
        """
        if not callable(fn):
            raise TypeError(f"Handler must be callable, got {type(fn)}")

        with self._lock:
            self._subs[name].append(fn)

        logger.debug(f"рџ“Ґ Subscribed to '{name}', total handlers: {len(self._subs[name])}")

    def publish(self, name: str, payload: Any = None) -> None:
        """
        рџ“¤ РћРїСѓР±Р»РёРєРѕРІР°С‚СЊ СЃРѕР±С‹С‚РёРµ

        Args:
            name: РРјСЏ СЃРѕР±С‹С‚РёСЏ
            payload: Р”Р°РЅРЅС‹Рµ РґР»СЏ РїРµСЂРµРґР°С‡Рё РѕР±СЂР°Р±РѕС‚С‡РёРєР°Рј
        """
        # РџРѕР»СѓС‡Р°РµРј РєРѕРїРёСЋ РїРѕРґРїРёСЃС‡РёРєРѕРІ РїРѕРґ Р±Р»РѕРєРёСЂРѕРІРєРѕР№
        with self._lock:
            subscribers = self._subs.get(name, []).copy()

        if not subscribers:
            logger.debug(f"рџ“¤ No subscribers for event '{name}'")
            return

        logger.debug(f"рџ“¤ Publishing '{name}' to {len(subscribers)} handlers")

        # Р’С‹Р·С‹РІР°РµРј РѕР±СЂР°Р±РѕС‚С‡РёРєРё Р‘Р•Р— Р±Р»РѕРєРёСЂРѕРІРєРё РґР»СЏ РёР·Р±РµР¶Р°РЅРёСЏ deadlock
        failed_count = 0
        for fn in subscribers:
            try:
                fn(payload)
            except Exception as e:
                failed_count += 1
                handler_name = getattr(fn, "__name__", fn.__class__.__name__)
                logger.error(
                    f"вќЊ Event '{name}' handler {handler_name} failed: {e}",
                    exc_info=True
                )

        if failed_count > 0:
            logger.warning(f"вљ пёЏ Event '{name}': {failed_count}/{len(subscribers)} handlers failed")

    def unsubscribe(self, name: str, fn: Callable[[Any], None]) -> bool:
        """
        рџ“¤ РћС‚РїРёСЃР°С‚СЊСЃСЏ РѕС‚ СЃРѕР±С‹С‚РёСЏ

        Returns:
            True РµСЃР»Рё РѕР±СЂР°Р±РѕС‚С‡РёРє Р±С‹Р» РЅР°Р№РґРµРЅ Рё СѓРґР°Р»РµРЅ
        """
        with self._lock:
            if name in self._subs and fn in self._subs[name]:
                self._subs[name].remove(fn)
                logger.debug(f"рџ“¤ Unsubscribed from '{name}', remaining: {len(self._subs[name])}")
                return True

        logger.debug(f"рџ“¤ Handler not found for '{name}'")
        return False

    # в”Ђв”Ђ РћРґРЅРѕСЂР°Р·РѕРІР°СЏ РїРѕРґРїРёСЃРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def subscribe_once(self, name: str, fn: Callable[[Any], None]) -> None:
        """
        рџ“Ґ РџРѕРґРїРёСЃР°С‚СЊСЃСЏ РЅР° СЃРѕР±С‹С‚РёРµ РѕРґРёРЅ СЂР°Р·: РїРѕСЃР»Рµ РїРµСЂРІРѕРіРѕ РІС‹Р·РѕРІР° РѕР±СЂР°Р±РѕС‚С‡РёРє СѓРґР°Р»СЏРµС‚СЃСЏ.
        """
        def wrapper(payload):
            try:
                fn(payload)
            finally:
                # РІР°Р¶РЅРѕ: РѕС‚РїРёСЃС‹РІР°РµРј РёРјРµРЅРЅРѕ wrapper
                self.unsubscribe(name, wrapper)

        self.subscribe(name, wrapper)

    # РђР»РёР°СЃ
    def once(self, name: str, fn: Callable[[Any], None]) -> None:
        self.subscribe_once(name, fn)

    # в”Ђв”Ђ РђР»РёР°СЃС‹ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃ on/emit СЃС‚РёР»РµРј в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def on(self, name: str, fn: Callable[[Any], None]) -> None:
        self.subscribe(name, fn)

    def emit(self, name: str, payload: Any = None) -> None:
        self.publish(name, payload)

    def off(self, name: str, fn: Callable[[Any], None]) -> bool:
        return self.unsubscribe(name, fn)

    # в”Ђв”Ђ РЈС‚РёР»РёС‚С‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def clear_event(self, name: str) -> int:
        """
        рџ—‘пёЏ РЈРґР°Р»РёС‚СЊ РІСЃРµС… РїРѕРґРїРёСЃС‡РёРєРѕРІ СЃРѕР±С‹С‚РёСЏ

        Returns:
            РљРѕР»РёС‡РµСЃС‚РІРѕ СѓРґР°Р»РµРЅРЅС‹С… РѕР±СЂР°Р±РѕС‚С‡РёРєРѕРІ
        """
        with self._lock:
            count = len(self._subs.get(name, []))
            if name in self._subs:
                del self._subs[name]

        logger.debug(f"рџ—‘пёЏ Cleared event '{name}', removed {count} handlers")
        return count

    def clear_all(self) -> int:
        """
        рџ—‘пёЏ РЈРґР°Р»РёС‚СЊ Р’РЎР• РїРѕРґРїРёСЃРєРё

        Returns:
            РћР±С‰РµРµ РєРѕР»РёС‡РµСЃС‚РІРѕ СѓРґР°Р»РµРЅРЅС‹С… РѕР±СЂР°Р±РѕС‚С‡РёРєРѕРІ
        """
        with self._lock:
            total_count = sum(len(handlers) for handlers in self._subs.values())
            self._subs.clear()

        logger.debug(f"рџ—‘пёЏ Cleared all events, removed {total_count} handlers")
        return total_count

    def list_events(self) -> Dict[str, int]:
        """
        рџ“‹ РџРѕР»СѓС‡РёС‚СЊ СЃРїРёСЃРѕРє РІСЃРµС… СЃРѕР±С‹С‚РёР№ Рё РєРѕР»РёС‡РµСЃС‚РІРѕ РїРѕРґРїРёСЃС‡РёРєРѕРІ

        Returns:
            Dict СЃ СЃРѕР±С‹С‚РёСЏРјРё Рё РєРѕР»РёС‡РµСЃС‚РІРѕРј РѕР±СЂР°Р±РѕС‚С‡РёРєРѕРІ
        """
        with self._lock:
            return {evt: len(handlers) for evt, handlers in self._subs.items()}

    def has_subscribers(self, name: str) -> bool:
        """
        вќ“ РџСЂРѕРІРµСЂРёС‚СЊ РµСЃС‚СЊ Р»Рё РїРѕРґРїРёСЃС‡РёРєРё РЅР° СЃРѕР±С‹С‚РёРµ

        Returns:
            True РµСЃР»Рё РµСЃС‚СЊ РїРѕРґРїРёСЃС‡РёРєРё
        """
        with self._lock:
            return len(self._subs.get(name, [])) > 0

    # в”Ђв”Ђ Debugging Рё СЃС‚Р°С‚РёСЃС‚РёРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def get_stats(self) -> Dict[str, Any]:
        """рџ“Љ РџРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚РёСЃС‚РёРєСѓ EventBus"""
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


# в”Ђв”Ђ Р“Р»РѕР±Р°Р»СЊРЅС‹Р№ instance (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_global_eventbus: Optional[EventBus] = None


def get_global_eventbus() -> EventBus:
    """рџЊђ РџРѕР»СѓС‡РёС‚СЊ РіР»РѕР±Р°Р»СЊРЅС‹Р№ EventBus (СЃРѕР·РґР°РµС‚СЃСЏ РїСЂРё РїРµСЂРІРѕРј РІС‹Р·РѕРІРµ)"""
    global _global_eventbus
    if _global_eventbus is None:
        _global_eventbus = EventBus()
        logger.info("рџЊђ Global EventBus created")
    return _global_eventbus


def set_global_eventbus(eventbus: EventBus) -> None:
    """рџЊђ РЈСЃС‚Р°РЅРѕРІРёС‚СЊ РіР»РѕР±Р°Р»СЊРЅС‹Р№ EventBus"""
    global _global_eventbus
    _global_eventbus = eventbus
    logger.info("рџЊђ Global EventBus set")


__all__ = ["EventBus", "get_global_eventbus", "set_global_eventbus"]









