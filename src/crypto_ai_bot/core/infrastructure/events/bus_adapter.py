from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

# Р‘Р°Р·РѕРІС‹Рµ РёРЅС‚РµСЂС„РµР№СЃС‹ (РєР°Рє Сѓ С‚РµР±СЏ РІ РїСЂРѕРµРєС‚Рµ)
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus, Event
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus


@runtime_checkable
class UnifiedEventBus(EventBusPort):
    """
    РђРґР°РїС‚РµСЂ, СѓРЅРёС„РёС†РёСЂСѓСЋС‰РёР№ РёРЅС‚РµСЂС„РµР№СЃС‹ СЂР°Р·РЅС‹С… СЂРµР°Р»РёР·Р°С†РёР№ С€РёРЅС‹:
    - AsyncEventBus (СЂР°Р±РѕС‚Р°РµС‚ СЃ Event)
    - RedisEventBus (СЂР°Р±РѕС‚Р°РµС‚ СЃ dict)
    Р’РЅРµС€РЅРµ РІСЃРµРіРґР° publish(dict) Рё on(dict-handler), РІРѕР·РІСЂР°С‰Р°РµС‚ None.
    """

    def __init__(self, implementation: AsyncEventBus | RedisEventBus):
        self._impl = implementation
        self._is_async = isinstance(implementation, AsyncEventBus)

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None:
        if self._is_async:
            # AsyncEventBus РјРѕР¶РµС‚ РІРѕР·РІСЂР°С‰Р°С‚СЊ Event/Dict вЂ” СЃС‚Р°РЅРґР°СЂС‚РёР·РёСЂСѓРµРј РґРѕ None
            await self._impl.publish(topic, payload, key=key)
            return
        # RedisEventBus СѓР¶Рµ РІРѕР·РІСЂР°С‰Р°РµС‚ None
        await self._impl.publish(topic, payload, key=key)

    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        if self._is_async:
            async def _wrap(evt: Event) -> None:
                # РР·РІР»РµРєР°РµРј С‚РѕР»СЊРєРѕ payload РёР· Event РґР»СЏ handler
                await handler(evt.payload)

            self._impl.on(topic, _wrap)
            return

        # RedisEventBus вЂ“ СѓР¶Рµ dict
        # Р”Р»СЏ RedisEventBus РЅСѓР¶РµРЅ РґСЂСѓРіРѕР№ wrapper
        async def _redis_wrap(data: Any) -> None:
            await handler(data)
    
        self._impl.on(topic, _redis_wrap)

    async def start(self) -> None:
        if hasattr(self._impl, "start"):
            await self._impl.start()

    async def close(self) -> None:
        if hasattr(self._impl, "close"):
            await self._impl.close()

    # РџСЂРѕРєСЃРёСЂСѓРµРј РѕСЃС‚Р°Р»СЊРЅРѕРµ Р±РµР· В«РјР°РіРёРёВ»
    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(self._impl, name)
