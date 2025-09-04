from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

try:
    # если есть штатные утилиты трейсинга — используем их
    from crypto_ai_bot.utils.trace import get_cid  # type: ignore
except Exception:  # noqa: BLE001
    get_cid = None  # type: ignore

# Локальная шина (in-memory)
from .bus import AsyncEventBus, Event

# Redis-реализация (может отсутствовать в минимальных развёртках)
try:
    from .redis_bus import RedisEventBus  # type: ignore
except Exception:  # noqa: BLE001
    RedisEventBus = None  # type: ignore


_log = get_logger("events.multi")


@dataclass(frozen=True)
class MirrorRules:
    """
    Правила зеркалирования «локальные → Redis».
    - include: список префиксов топиков для зеркалирования (если пусто — значит *все*)
    - exclude: список префиксов, которые нельзя зеркалить (преимущественно над include)
    - filter_by_key: опциональный фильтр по ключу события
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    filter_by_key: Callable[[str | None], bool] | None = None

    def match(self, topic: str, key: str | None) -> bool:
        if any(topic.startswith(p) for p in self.exclude):
            return False
        if self.include and not any(topic.startswith(p) for p in self.include):
            return False
        if self.filter_by_key and not self.filter_by_key(key):
            return False
        return True


class MultiEventBus:
    """
    Фасад над двумя шинами:
      - локальная память (AsyncEventBus) — обработчики исполняются сразу;
      - RedisEventBus — зеркалирование «во внешний мир» (одностороннее, локал→Redis).

    Публичный API совместим с AsyncEventBus:
      - start()/close()
      - subscribe()/on(), subscribe_wildcard()/on_wildcard(), subscribe_dlq()
      - publish(topic, payload, key=None)

    Примечания:
      • Вход из Redis обратно в локальную шину **не** подключаем (по ТЗ: «зеркалятся в Redis»).
      • trace_id автоматически вкалываем в payload, если отсутствует.
    """

    def __init__(
        self,
        *,
        local: AsyncEventBus,
        remote: RedisEventBus | None = None,
        rules: MirrorRules | None = None,
        inject_trace: bool = True,
    ) -> None:
        self._local = local
        self._remote = remote
        self._rules = rules or MirrorRules()
        self._inject_trace = bool(inject_trace)
        self._started = False

    # ---------- подписки (проксируем в локальную шину) ----------
    def subscribe(self, topic: str, handler: Callable[[Event], Any]) -> None:
        self._local.subscribe(topic, handler)

    def on(self, topic: str, handler: Callable[[Event], Any]) -> None:
        self.subscribe(topic, handler)

    def subscribe_wildcard(self, pattern: str, handler: Callable[[Event], Any]) -> None:
        self._local.subscribe_wildcard(pattern, handler)

    def on_wildcard(self, pattern: str, handler: Callable[[Event], Any]) -> None:
        self.subscribe_wildcard(pattern, handler)

    def subscribe_dlq(self, handler: Callable[[Event], Any]) -> None:
        self._local.subscribe_dlq(handler)

    def attach_logger_dlq(self) -> None:
        self._local.attach_logger_dlq()

    # ---------- жизненный цикл ----------
    async def start(self) -> None:
        if self._started:
            return
        await self._local.start()
        if self._remote and hasattr(self._remote, "start"):
            try:
                await self._remote.start()
            except Exception:  # noqa: BLE001
                _log.warning("multi_bus_remote_start_failed", exc_info=True)
        self._started = True
        _log.info("multi_bus_started", extra={"remote": bool(self._remote)})

    async def close(self) -> None:
        self._started = False
        try:
            await self._local.close()
        finally:
            if self._remote and hasattr(self._remote, "close"):
                try:
                    await self._remote.close()
                except Exception:  # noqa: BLE001
                    _log.debug("multi_bus_remote_close_failed", exc_info=True)
        _log.info("multi_bus_closed")

    # ---------- публикация ----------
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> dict[str, Any]:
        # Вкалываем trace_id (идемпотентно)
        if self._inject_trace and "trace_id" not in payload:
            try:
                if get_cid:
                    payload = {**payload, "trace_id": str(get_cid())}
            except Exception:  # noqa: BLE001
                pass

        # 1) локальная доставка — синхронно
        res_local = await self._local.publish(topic, payload, key=key)

        # 2) зеркалирование в Redis — best effort
        if self._remote and self._rules.match(topic, key):
            try:
                await self._remote.publish(topic, payload, key=key)
                inc("bus_mirror_ok_total", topic=topic)
            except Exception:  # noqa: BLE001
                inc("bus_mirror_err_total", topic=topic)
                _log.error("multi_bus_mirror_failed", extra={"topic": topic}, exc_info=True)

        return {"ok": True, "delivered_local": res_local.get("delivered", 0), "mirrored": bool(self._remote)}

    # ---------- утилиты ----------
    @staticmethod
    def from_urls(
        *,
        redis_url: str | None,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        inject_trace: bool = True,
        dedupe_local: bool = True,
        topic_concurrency: int = 32,
    ) -> "MultiEventBus":
        """
        Быстрый конструктор:
          - создаёт локальную шину (с опциональной дедупликацией),
          - при наличии redis_url создаёт RedisEventBus для зеркалирования.
        """
        local = AsyncEventBus(enable_dedupe=dedupe_local, topic_concurrency=topic_concurrency)
        remote = None
        if redis_url and RedisEventBus is not None:
            try:
                remote = RedisEventBus(redis_url)
            except Exception:  # noqa: BLE001
                _log.warning("multi_bus_redis_init_failed", exc_info=True)
        rules = MirrorRules(
            include=tuple(include or ()),
            exclude=tuple(exclude or ()),
            filter_by_key=None,
        )
        return MultiEventBus(local=local, remote=remote, rules=rules, inject_trace=inject_trace)
