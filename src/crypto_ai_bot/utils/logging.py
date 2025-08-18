# src/crypto_ai_bot/utils/logging.py
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict, Optional

_configured = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # прокидываем extra, если они были
        for k, v in record.__dict__.items():
            if k in ("args", "created", "exc_info", "exc_text", "filename", "funcName",
                     "levelname", "levelno", "lineno", "module", "msecs", "msg",
                     "name", "pathname", "process", "processName", "relativeCreated",
                     "stack_info", "thread", "threadName"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except Exception:
                payload[k] = str(v)
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")


def init(*, level: str = "INFO", json_format: bool = False, logger_name: Optional[str] = None) -> None:
    """
    Инициализация логгера. ВАЖНО: не читает ENV — параметры передаются извне (server.py -> Settings).
    """
    global _configured
    if _configured:
        # уже настроено — просто обновим уровень
        set_level(level, logger_name=logger_name)
        return

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    logger.setLevel(level.upper())

    # убираем существующие хендлеры у корневого, чтобы не дублировать вывод
    if not logger_name:
        for h in list(logger.handlers):
            logger.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level.upper())
    handler.setFormatter(_JsonFormatter() if json_format else _TextFormatter())
    logger.addHandler(handler)

    # чтобы дочерние логгеры не плодили дубли, отключаем propagate у корневого
    if not logger_name:
        logger.propagate = False

    _configured = True


def set_level(level: str, *, logger_name: Optional[str] = None) -> None:
    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    logger.setLevel(level.upper())
    for h in logger.handlers:
        try:
            h.setLevel(level.upper())
        except Exception:
            pass


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
