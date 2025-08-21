from __future__ import annotations
import sys
import json
import logging
import contextvars
from datetime import datetime, timezone
from typing import Any


# Контекстная переменная для корреляции (trace_id)
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


class JsonFormatter(logging.Formatter):
    """Форматер, выводящий логи в JSON: время (UTC), уровень, логгер, сообщение, trace_id."""
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = _trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str | None = None) -> logging.Logger:
    """Возвращает логгер с JSON-форматером и выводом в STDOUT."""
    logger_name = name or __name__
    logger = logging.getLogger(logger_name)
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    return logger


def set_trace_id(trace_id: str | None) -> None:
    """Устанавливает trace_id в контекст логирования."""
    _trace_id_var.set(trace_id)


def get_trace_id() -> str | None:
    """Возвращает текущий trace_id из контекста (если установлен)."""
    return _trace_id_var.get()