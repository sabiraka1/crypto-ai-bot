# src/crypto_ai_bot/utils/logging.py
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "ts": record.created,
        }
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        if record.__dict__.get("extra"):
            data["extra"] = record.__dict__["extra"]
        return json.dumps(data, ensure_ascii=False)

def init(level: str | None = None, json_logs: bool | None = None) -> None:
    """
    Инициализация логирования для приложения/uvicorn.
    Источники конфигурации:
      - env LOG_LEVEL (INFO|DEBUG|...)
      - env LOG_JSON ("1"/"true") — включить JSON-формат
    """
    lvl_name = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    lvl = _LEVELS.get(lvl_name, logging.INFO)
    use_json = (str(json_logs if json_logs is not None else os.getenv("LOG_JSON", "0"))).lower() in ("1", "true", "yes")

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(lvl)

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
    root.addHandler(handler)

    # популярные логгеры
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).setLevel(lvl)
