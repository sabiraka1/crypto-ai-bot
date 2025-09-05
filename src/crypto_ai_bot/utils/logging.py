"""
Structured JSON logging with correlation ID support.

Features:
- JSON formatting for log aggregation systems
- Automatic secret masking
- Correlation ID integration
- Async-safe with ContextVar
- Idempotent configuration
"""
from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Final, Optional

# ============= CORRELATION ID (async-safe) =============

_CORRELATION_ID: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def set_correlation_id(value: Optional[str]) -> None:
    """Set correlation ID in async-safe context"""
    _CORRELATION_ID.set(value)


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID from context"""
    return _CORRELATION_ID.get()


# ============= JSON FORMATTER =============

class JsonFormatter(logging.Formatter):
    """
    JSON formatter with secret masking and correlation ID support.

    Produces structured logs for easy parsing and analysis.
    """

    # Keys to mask in logs for security
    SENSITIVE_KEYS: Final[set[str]] = {
        # API credentials
        "api_key",
        "api_secret",
        "api_token",
        "secret_key",
        "private_key",

        # Auth tokens
        "password",
        "token",
        "authorization",
        "access_token",
        "refresh_token",
        "bearer_token",

        # Service tokens
        "telegram_token",
        "telegram_bot_token",
        "webhook_secret",

        # Generic secrets
        "secret",
        "credential",
        "passphrase",
    }

    # Standard LogRecord attributes to exclude from extra fields
    STANDARD_ATTRS: Final[set[str]] = {
        "args", "asctime", "created", "exc_info", "exc_text",
        "filename", "funcName", "levelname", "levelno", "lineno",
        "module", "msecs", "message", "msg", "name", "pathname",
        "process", "processName", "relativeCreated", "stack_info",
        "thread", "threadName", "taskName",
    }

    def __init__(self, *, include_timestamp: bool = True, include_location: bool = False):
        """
        Initialize formatter.

        Args:
            include_timestamp: Include timestamp in output
            include_location: Include file/line info
        """
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_location = include_location

    def format(self, record: logging.LogRecord) -> str:
        """Format LogRecord as JSON string"""
        # Base payload
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Timestamp (UTC, tz-aware)
        if self.include_timestamp:
            payload["timestamp"] = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            payload["ts_unix"] = record.created  # Unix timestamp for metrics

        # Location info (useful for debugging)
        if self.include_location:
            payload["location"] = f"{record.filename}:{record.lineno}"
            payload["function"] = record.funcName

        # Correlation/trace ID: record attribute > context > None
        cid = (
            getattr(record, "correlation_id", None)
            or getattr(record, "trace_id", None)
            or get_correlation_id()
        )
        if cid:
            payload["trace_id"] = cid

        # Add extra fields (from logging.info(..., extra={...}))
        for key, value in record.__dict__.items():
            # Skip private, standard, and already included
            if key.startswith("_") or key in self.STANDARD_ATTRS:
                continue
            if key in ("correlation_id", "trace_id"):
                continue  # Already handled above

            # Mask sensitive fields
            if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                payload[key] = "***MASKED***"
            else:
                # Ensure JSON serializable
                payload[key] = self._make_json_safe(value)

        # Exception info
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None

        return json.dumps(payload, ensure_ascii=False, default=str)

    def _make_json_safe(self, value: Any) -> Any:
        """Convert value to JSON-serializable format (with recursive masking for dicts)"""
        # Try direct serialization first
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            pass

        # Dicts: recurse + mask sensitive keys
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if any(s in str(k).lower() for s in self.SENSITIVE_KEYS):
                    out[k] = "***MASKED***"
                else:
                    out[k] = self._make_json_safe(v)
            return out

        # Objects with attributes
        if hasattr(value, "__dict__"):
            return {k: str(v) for k, v in value.__dict__.items() if not k.startswith("_")}

        # Iterables (lists, sets, tuples) but not strings/bytes
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            return [self._make_json_safe(v) for v in value]

        # Fallback to string
        return str(value)


# ============= HANDLER CREATION =============

def _create_stream_handler(
    stream=None,
    formatter: Optional[logging.Formatter] = None
) -> logging.StreamHandler:
    """Create configured stream handler"""
    handler = logging.StreamHandler(stream=stream or sys.stdout)
    handler.setFormatter(formatter or JsonFormatter())
    return handler


def _level_from_env(default: str = "INFO") -> int:
    """Get log level from environment variable"""
    level_str = os.getenv("LOG_LEVEL", default).upper().strip()

    # Map string to logging constant
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "FATAL": logging.CRITICAL,
    }

    return level_map.get(level_str, logging.INFO)


# ============= CONFIGURATION =============

def configure_root(
    level: Optional[int] = None,
    formatter: Optional[logging.Formatter] = None,
    remove_existing: bool = False
) -> None:
    """
    Configure root logger with JSON formatting.

    Idempotent - won't duplicate handlers on multiple calls.

    Args:
        level: Log level (uses LOG_LEVEL env if None)
        formatter: Custom formatter (uses JsonFormatter if None)
        remove_existing: Remove existing handlers before adding new
    """
    root = logging.getLogger()

    # Set level
    if level is None:
        level = _level_from_env()
    root.setLevel(level)

    # Remove existing handlers if requested
    if remove_existing:
        root.handlers.clear()

    # Detect existing stream handler(s) and whether any has JsonFormatter
    has_stream_handler = False
    has_json_stream = False

    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            has_stream_handler = True
            if isinstance(handler.formatter, JsonFormatter):
                has_json_stream = True
                handler.setLevel(level)  # keep level in sync
            # If a custom formatter is provided, update existing handler
            if formatter is not None:
                handler.setFormatter(formatter)
                has_json_stream = isinstance(formatter, JsonFormatter)

    # If no stream handler at all — add one (with provided formatter or Json)
    if not has_stream_handler:
        handler = _create_stream_handler(formatter=formatter)
        handler.setLevel(level)
        root.addHandler(handler)
        has_json_stream = isinstance(handler.formatter, JsonFormatter)

    # If we still don't have JSON and no custom formatter was provided,
    # add a dedicated JSON stream handler to guarantee structured logs.
    if not has_json_stream and formatter is None:
        handler = _create_stream_handler(formatter=JsonFormatter())
        handler.setLevel(level)
        root.addHandler(handler)

    # Tame noisy third-party loggers
    _configure_third_party_loggers()


def _configure_third_party_loggers() -> None:
    """Reduce noise from third-party libraries"""
    noisy_loggers = [
        "urllib3",
        "requests",
        "httpx",
        "asyncio",
        "ccxt",
        "websockets",
        "telegram",
    ]

    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)


def get_logger(
    name: str,
    *,
    level: Optional[int] = None,
    propagate: bool = False
) -> logging.Logger:
    """
    Get configured logger with JSON formatting.

    Args:
        name: Logger name (usually __name__)
        level: Log level (uses LOG_LEVEL env if None)
        propagate: Whether to propagate to parent logger

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Set level
    if level is None:
        level = _level_from_env()
    logger.setLevel(level)

    # Add handler if doesn't have one
    if not logger.handlers:
        handler = _create_stream_handler()
        handler.setLevel(level)
        logger.addHandler(handler)

    # Control propagation
    logger.propagate = propagate

    return logger


# ============= CONTEXT HELPERS =============

def add_context_fields(**fields: Any) -> dict[str, Any]:
    """
    Create extra dict with context fields for logging.

    Automatically adds correlation_id if available.

    Usage:
        logger.info("Processing", extra=add_context_fields(
            symbol="BTC/USDT",
            amount=100
        ))
    """
    extra = dict(fields)

    # Add correlation ID if available
    if cid := get_correlation_id():
        extra["correlation_id"] = cid

    return extra


# ============= STRUCTURED LOGGING HELPERS =============

class StructuredLogger:
    """
    Wrapper for structured logging with automatic context.

    Usage:
        slog = StructuredLogger(logger, symbol="BTC/USDT")
        slog.info("Order placed", amount=100, price=50000)
        # Automatically includes symbol and correlation_id
    """

    def __init__(self, logger: logging.Logger, **default_fields: Any):
        """
        Initialize with logger and default fields.

        Args:
            logger: Base logger
            **default_fields: Fields to include in every log
        """
        self.logger = logger
        self.default_fields = default_fields

    def _log(self, level: int, msg: str, **fields: Any) -> None:
        """Internal log method"""
        extra = {**self.default_fields, **fields}

        # Add correlation ID
        if cid := get_correlation_id():
            extra["correlation_id"] = cid

        self.logger.log(level, msg, extra=extra)

    def debug(self, msg: str, **fields: Any) -> None:
        self._log(logging.DEBUG, msg, **fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._log(logging.INFO, msg, **fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._log(logging.WARNING, msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._log(logging.ERROR, msg, **fields)

    def critical(self, msg: str, **fields: Any) -> None:
        self._log(logging.CRITICAL, msg, **fields)

    def exception(self, msg: str, **fields: Any) -> None:
        """Log with exception info"""
        extra = {**self.default_fields, **fields}
        if cid := get_correlation_id():
            extra["correlation_id"] = cid
        self.logger.exception(msg, extra=extra)


# ============= PERFORMANCE LOGGING =============

class LogTimer:
    """
    Context manager for timing operations.

    Usage:
        with LogTimer(logger, "database_query"):
            # ... operation ...
        # Logs: "database_query completed in 0.123s"
    """

    def __init__(
        self,
        logger: logging.Logger,
        operation: str,
        level: int = logging.INFO,
        **fields: Any
    ):
        self.logger = logger
        self.operation = operation
        self.level = level
        self.fields = fields
        self.start_time: Optional[float] = None

    def __enter__(self) -> "LogTimer":
        import time
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        import time
        if self.start_time is None:
            return

        duration = time.perf_counter() - self.start_time

        extra = {
            "operation": self.operation,
            "duration_ms": round(duration * 1000, 2),
            **self.fields
        }

        if cid := get_correlation_id():
            extra["correlation_id"] = cid

        if exc_type is None:
            self.logger.log(
                self.level,
                f"{self.operation} completed in {duration:.3f}s",
                extra=extra
            )
        else:
            extra["error"] = str(exc_val)
            extra["error_type"] = exc_type.__name__
            self.logger.error(
                f"{self.operation} failed after {duration:.3f}s",
                extra=extra
            )


# ============= INITIALIZATION =============

# Auto-configure if running as main module
if __name__ != "__main__":
    # Only auto-configure in production
    if os.getenv("AUTO_CONFIGURE_LOGGING", "true").lower() == "true":
        configure_root()


# ============= EXPORT =============

__all__ = [
    # Core functions
    "get_correlation_id",
    "set_correlation_id",
    "get_logger",
    "configure_root",

    # Formatter
    "JsonFormatter",

    # Helpers
    "add_context_fields",
    "StructuredLogger",
    "LogTimer",
]
