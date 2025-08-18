# src/crypto_ai_bot/utils/logging.py
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional
import contextvars
from datetime import datetime, timezone

# Контекст корреляции (можно выставлять вручную в UC/обработчиках)
_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("correlation_id", default=None)
_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)


def set_correlation_id(value: Optional[str]) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def set_request_id(value: Optional[str]) -> None:
    _request_id.set(value)


def get_request_id() -> Optional[str]:
    return _request_id.get()


class _JsonFormatter(logging.Formatter):
    def __init__(self, app_name: str = "crypto-ai-bot") -> None:
        super().__init__()
        self.app_name = app_name

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        base: Dict[str, Any] = {
            "ts": ts,
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "app": self.app_name,
        }
        # где доступно — добавляем стандартные поля
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        corr = get_correlation_id()
        if corr:
            base["correlation_id"] = corr
        rid = get_request_id()
        if rid:
            base["request_id"] = rid

        # Учитываем extra=... (record.__dict__ может содержать сервисные ключи)
        for k, v in record.__dict__.items():
            if k in ("args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
                     "levelname", "levelno", "lineno", "module", "msecs", "message", "msg",
                     "name", "pathname", "process", "processName", "relativeCreated", "stack_info",
                     "thread", "threadName"):
                continue
            # пропускаем встроенные на низком уровне
            if k.startswith("_"):
                continue
            # не перетираем базовые ключи
            if k in base:
                continue
            try:
                json.dumps({k: v})  # проверка сериализуемости
                base[k] = v
            except TypeError:
                base[k] = str(v)

        return json.dumps(base, ensure_ascii=False)


def init(level: Optional[str] = None, app_name: str = "crypto-ai-bot") -> None:
    """
    Инициализирует глобальный JSON-логгер.
    Совместимо с вызовом из app/server.py: init_logging()

    ENV:
      LOG_LEVEL=INFO|DEBUG|WARNING|ERROR (по умолчанию INFO)
    """
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    # корневой логгер
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # очищаем старые хендлеры (uvicorn/gunicorn может добавить свои)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter(app_name=app_name))
    root.addHandler(handler)

    # Уменьшаем болтливость некоторых либ, если они подтянуты
    for noisy in ("uvicorn.access", "uvicorn.error", "asyncio", "httpx", "urllib3"):
        lg = logging.getLogger(noisy)
        if lg.level == logging.NOTSET:
            lg.setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# Удобные шорткаты (если хочется точечно логировать без явного get_logger)
def info(msg: str, **extra: Any) -> None:
    logging.getLogger("app").info(msg, extra=extra)


def warning(msg: str, **extra: Any) -> None:
    logging.getLogger("app").warning(msg, extra=extra)


def error(msg: str, **extra: Any) -> None:
    logging.getLogger("app").error(msg, extra=extra)


def debug(msg: str, **extra: Any) -> None:
    logging.getLogger("app").debug(msg, extra=extra)
