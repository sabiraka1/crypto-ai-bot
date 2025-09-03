from __future__ import annotations

import json
import logging
import sys
from typing import Any


__all__ = ["get_correlation_id", "get_logger", "set_correlation_id"]

_CORRELATION_ID: str | None = None

def set_correlation_id(value: str | None) -> None:
    global _CORRELATION_ID
    _CORRELATION_ID = value

def get_correlation_id() -> str | None:
    return _CORRELATION_ID


class JsonFormatter(logging.Formatter):
    SENSITIVE_KEYS = {"api_key", "api_secret", "password", "token", "authorization"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = getattr(record, "correlation_id", None) or get_correlation_id()
        if cid:
            payload["correlation_id"] = cid

        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("_"):
                continue
            if key in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename", "levelname", "levelno",
                "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread", "threadName",
            }:
                continue
            if key in self.SENSITIVE_KEYS:
                payload[key] = "***"
            else:
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
    """Return a JSON-structured logger. Adds a single StreamHandler if none exist."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger
