# src/crypto_ai_bot/utils/logging.py
from __future__ import annotations

import logging
import sys
from typing import Optional

_request_id: Optional[str] = None
_correlation_id: Optional[str] = None

class _CtxFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id or "-"
        record.correlation_id = _correlation_id or "-"
        return True

def set_request_id(v: Optional[str]) -> None:
    global _request_id
    _request_id = v

def set_correlation_id(v: Optional[str]) -> None:
    global _correlation_id
    _correlation_id = v

def init(level: str = "INFO", json_format: bool = False) -> None:
    """
    Инициализация логгера без чтения ENV.
    level — строка уровня (DEBUG/INFO/…)
    json_format — если True, выводим компактный JSON (минимум полей).
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_CtxFilter())

    if json_format:
        try:
            import json
            class _JsonFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    payload = {
                        "level": record.levelname,
                        "msg": record.getMessage(),
                        "logger": record.name,
                        "request_id": getattr(record, "request_id", "-"),
                        "correlation_id": getattr(record, "correlation_id", "-"),
                    }
                    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            handler.setFormatter(_JsonFormatter())
        except Exception:
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s | %(message)s"))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s cid=%(correlation_id)s] | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root.addHandler(handler)
