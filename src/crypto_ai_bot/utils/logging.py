from __future__ import annotations
import json
import logging
import sys
import time
import uuid
from typing import Any, Dict, Optional
import contextvars

# Текущий request-id (проставляет мидлварь)
REQUEST_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("REQUEST_ID", default=None)

_SENSITIVE_KEYS = ("token", "secret", "password", "api_key", "apikey", "authorization", "auth")

def _mask_value(v: Any) -> Any:
    if v is None:
        return None
    s = str(v)
    if len(s) <= 6:
        return "***"
    return s[:3] + "***" + s[-2:]

def mask_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        if any(sk in k.lower() for sk in _SENSITIVE_KEYS):
            out[k] = _mask_value(v)
        else:
            out[k] = v
    return out

class JsonFormatter(logging.Formatter):
    def __init__(self, *, app: str = "crypto-ai-bot", env: str = "dev"):
        super().__init__()
        self.app = app
        self.env = env

    def format(self, record: logging.LogRecord) -> str:
        rid = REQUEST_ID.get()
        base = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "app": self.app,
            "env": self.env,
        }
        if rid:
            base["request_id"] = rid
        # приклеим extra-данные (если передавали через logger.bind / extra=...)
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            base.update(mask_dict(record.extra))
        # Исключение — компактно
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)

def setup_json_logging(settings: Any) -> None:
    """Включаем JSON-логирование для всего приложения (root + uvicorn)."""
    app = getattr(settings, "APP_NAME", "crypto-ai-bot")
    env = getattr(settings, "ENV", getattr(settings, "MODE", "dev"))
    level = getattr(settings, "LOG_LEVEL", "INFO")

    fmt = JsonFormatter(app=app, env=env)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Шум uvicorn access — оставляем (но в JSON)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error", "gunicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [handler]
        lg.setLevel(level)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
