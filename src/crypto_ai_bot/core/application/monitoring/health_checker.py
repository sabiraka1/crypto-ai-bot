from __future__ import annotations
import logging
from typing import Any

try:
    from crypto_ai_bot.utils.logging import get_logger as _get_logger
    from crypto_ai_bot.utils.metrics import inc as _inc
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
        return _get_logger(name=name, level=level)
    def inc(name: str, **labels: Any) -> None:
        _inc(name, **labels)
except Exception:
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        return logger
    def inc(name: str, **labels: Any) -> None:
        return None



class HealthChecker:
    def __init__(self, *args, **kwargs):
        pass
    async def ready(self) -> bool:
        return True
