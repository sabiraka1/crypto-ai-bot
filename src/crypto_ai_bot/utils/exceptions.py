## `utils/exceptions.py`
from __future__ import annotations

__all__ = [
    "BrokerError",
    "CircuitOpenError",
    "IdempotencyError",
    "TradingError",
    "TransientError",
    "ValidationError",
]


class TradingError(Exception):
    """Base domain error for the trading system."""


class ValidationError(TradingError):
    """Raised on configuration/DTO validation failures (do not retry)."""


class BrokerError(TradingError):
    """Raised when an exchange/broker operation fails (usually not retriable)."""


class TransientError(TradingError):
    """Raised on transient conditions (timeouts, rate limits, temporary network).
    Safe to retry with backoff.
    """


class IdempotencyError(TradingError):
    """Raised when an idempotency constraint is violated (duplicate key, etc.)."""


class CircuitOpenError(TradingError):
    """Raised when a circuit breaker is OPEN and calls are not allowed."""
