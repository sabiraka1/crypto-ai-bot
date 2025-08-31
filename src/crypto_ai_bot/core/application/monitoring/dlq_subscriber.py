from __future__ import annotations

from typing import Any, Callable, Awaitable, Optional, Dict

# мягкие зависимости
try:
    from crypto_ai_bot.utils.logging import get_logger  # type: ignore
except Exception:  # pragma: no cover
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

try:
    from crypto_ai_bot.utils.metrics import inc  # type: ignore
except Exception:  # pragma: no cover
    def inc(_name: str, **_labels: Any) -> None:  # no-op
        pass

_log = get_logger("monitoring.dlq")


async def _log_dlq(evt: Any) -> None:
    """
    Универсальный обработчик DLQ-событий.
    evt может быть:
      - объект с полями .topic/.payload
      - или dict с ключами "topic"/"payload"
    """
    try:
        topic = getattr(evt, "topic", None) or (evt.get("topic") if isinstance(evt, dict) else "__unknown__")
        payload: Dict[str, Any] = getattr(evt, "payload", None) or (evt.get("payload") if isinstance(evt, dict) else {})
        original = payload.get("original_topic") or topic
        _log.error("DLQ_EVENT", extra={"original_topic": original, "payload": payload})
        inc("bus_dlq_events_total", original_topic=str(original))
    except Exception:
        # не эскалируем, DLQ — best effort
        pass


def attach_dlq_subscriber(bus: Any) -> None:
    """
    Подключает обработчик к DLQ с учётом разных реализаций шины:
      1) если есть bus.subscribe_dlq(...) — используем её,
      2) иначе пробуем подписаться на спец-топики "__dlq__" и "dlq"
         (через bus.on(...) или bus.subscribe(...)).
    """
    # 1) нативная поддержка DLQ
    if hasattr(bus, "subscribe_dlq"):
        try:
            bus.subscribe_dlq(_log_dlq)  # type: ignore[arg-type]
            _log.info("dlq_subscriber_attached", extra={"mode": "subscribe_dlq"})
            return
        except Exception as exc:
            _log.error("dlq_subscribe_failed", extra={"error": str(exc)})

    # 2) через топики "__dlq__" или "dlq"
    def _attach_by_topic(topic: str) -> bool:
        for method in ("on", "subscribe"):
            if hasattr(bus, method):
                try:
                    getattr(bus, method)(topic, _log_dlq)  # type: ignore[misc]
                    _log.info("dlq_subscriber_attached", extra={"mode": f"{method}:{topic}"})
                    return True
                except Exception as exc:
                    _log.error("dlq_subscribe_via_topic_failed", extra={"topic": topic, "error": str(exc)})
        return False

    if _attach_by_topic("__dlq__"):
        return
    _attach_by_topic("dlq")
