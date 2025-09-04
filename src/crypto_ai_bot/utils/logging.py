from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Final

__all__ = [
    "get_correlation_id",
    "get_logger",
    "set_correlation_id",
    "configure_root",
]

# -------- correlation-id (простая глобалка; при желании легко заменить на contextvars) --------
_CORRELATION_ID: str | None = None


def set_correlation_id(value: str | None) -> None:
    global _CORRELATION_ID
    _CORRELATION_ID = value


def get_correlation_id() -> str | None:
    return _CORRELATION_ID


class JsonFormatter(logging.Formatter):
    """Минималистичный JSON-форматтер со скрытием секретов и поддержкой correlation_id."""

    # ключи, которые маскируем в логах
    SENSITIVE_KEYS: Final[set[str]] = {
        "api_key",
        "api_secret",
        "password",
        "token",
        "authorization",
        "access_token",
        "refresh_token",
        "secret",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": record.created,  # unix seconds (float)
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # correlation id: берём либо из record, либо из глобалки
        cid = getattr(record, "correlation_id", None) or get_correlation_id()
        if cid:
            payload["correlation_id"] = cid

        # переносим безопасные поля из record.__dict__ (переданные через extra=...)
        skip = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in skip:
                continue
            if key in self.SENSITIVE_KEYS:
                payload[key] = "***"
            else:
                # типы приводим к JSON-дружественным
                try:
                    json.dumps(value)
                    payload[key] = value
                except Exception:
                    payload[key] = str(value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


def _make_stream_handler() -> logging.Handler:
    h = logging.StreamHandler(stream=sys.stdout)
    h.setFormatter(JsonFormatter())
    return h


def _level_from_env(default: str = "INFO") -> int:
    level_s = os.getenv("LOG_LEVEL", default).upper().strip()
    return getattr(logging, level_s, logging.INFO)


def configure_root(level: int | None = None) -> None:
    """
    Идемпотентная настройка корневого логгера:
      - JSON-формат в stdout,
      - уровень из LOG_LEVEL (или аргумента),
      - без дублирования хендлеров.
    """
    root = logging.getLogger()
    root.setLevel(level if level is not None else _level_from_env())

    # добавляем StreamHandler только если ещё не стоит наш форматтер
    has_stream = any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    if not has_stream:
        root.addHandler(_make_stream_handler())

    # не ломаем существующие форматтеры/хендлеры — если есть, просто обновим уровень
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout:
            if not isinstance(h.formatter, JsonFormatter):
                h.setFormatter(JsonFormatter())
        h.setLevel(root.level)


def get_logger(name: str, *, level: int | None = None) -> logging.Logger:
    """
    Возвращает именованный логгер c JSON-форматтером.
    Если у логгера нет StreamHandler — добавляем свой (stdout).
    """
    logger = logging.getLogger(name)
    if level is None:
        level = _level_from_env()
    logger.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(_make_stream_handler())
        logger.propagate = False  # не дублировать в root

    return logger
