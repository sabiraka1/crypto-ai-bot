# src/crypto_ai_bot/core/brokers/base.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable, Any


class ExchangeError(Exception):
    """Базовая ошибка биржи."""


class TransientExchangeError(ExchangeError):
    """Временная ошибка (сеть/таймаут/429/5xx) — можно ретраить."""


class PermanentExchangeError(ExchangeError):
    """Постоянная ошибка (валидация/неправильный символ и т.п.)."""


@runtime_checkable
class ExchangeInterface(Protocol):
    """Единый контракт для брокеров (live/paper/backtest)."""

    # OHLCV: [[ts_ms, open, high, low, close, volume], ...] по возрастанию ts
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]: ...

    # Ticker: словарь с хотя бы last/close/bid/ask
    def fetch_ticker(self, symbol: str) -> dict: ...

    # Создание ордера (market/limit)
    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> dict: ...

    def cancel_order(self, order_id: str) -> dict: ...

    def fetch_balance(self) -> dict: ...


# ---- фабрика брокеров ---------------------------------------------------------

def create_broker(cfg: Any) -> ExchangeInterface:
    """
    Фабрика, выбирающая реализацию по cfg.MODE:
    - "live"     → CcxtExchange
    - "paper"    → PaperExchange
    - "backtest" → BacktestExchange
    """
    mode = str(getattr(cfg, "MODE", "paper")).lower()

    if mode == "live":
        from .ccxt_exchange import CcxtExchange  # lazy import, чтобы избежать циклов
        return CcxtExchange.from_settings(cfg)

    if mode == "paper":
        from .paper_exchange import PaperExchange
        return PaperExchange.from_settings(cfg)

    if mode == "backtest":
        from .backtest_exchange import BacktestExchange
        return BacktestExchange.from_settings(cfg)

    raise ValueError(f"Unknown MODE: {mode!r}")
