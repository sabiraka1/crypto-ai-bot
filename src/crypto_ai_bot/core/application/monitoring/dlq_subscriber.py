from __future__ import annotations
import logging
from typing import Any, Awaitable, Callable

try:
    from crypto_ai_bot.utils.logging import get_logger as _get_logger
    from crypto_ai_bot.utils.metrics import inc as _inc
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
        return _get_logger(name=name, level=level)
    def inc(name: str, **labels: Any) -> None:
        _inc(name, **labels)
except Exception:
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:  # type: ignore[misc]
        logger = logging.getLogger(name)
        logger.setLevel(level)
        return logger
    def inc(name: str, **labels: Any) -> None:  # no-op
        return None

async def wire_dlq(bus: Any) -> None:
    log = get_logger("dlq")

    async def _log_dlq(evt: Any) -> None:
        payload: dict[str, Any] = getattr(evt, "payload", None) or (evt if isinstance(evt, dict) else {})
        log.error("dlq_event", extra={"topic": getattr(evt, "topic", "unknown"), "payload": payload})
        inc("dlq_event", topic=str(getattr(evt, "topic", "unknown")))

    try:
        if hasattr(bus, "subscribe_dlq"):
            bus.subscribe_dlq(_log_dlq)  # type: ignore[attr-defined]
        for method in ("on", "subscribe"):
            if hasattr(bus, method):
                for topic in ("error", "trade.failed", "orchestrator.error"):
                    getattr(bus, method)(topic, _log_dlq)  # type: ignore[attr-defined]
    except Exception:
        log.exception("wire_dlq_failed")
