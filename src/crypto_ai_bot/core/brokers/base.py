from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable, Optional, Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.events import BusProtocol


class ExchangeError(Exception): ...
class TransientExchangeError(ExchangeError): ...
class PermanentExchangeError(ExchangeError): ...


@runtime_checkable
class ExchangeInterface(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]: ...
    def fetch_ticker(self, symbol: str) -> dict: ...
    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> dict: ...
    def fetch_balance(self) -> dict: ...
    def cancel_order(self, order_id: str) -> dict: ...
    # мягкая интеграция событиями (не обязательно реализовывать)
    def set_bus(self, bus: Optional[BusProtocol]) -> None: ...


def create_broker(cfg: Settings, *, bus: Optional[BusProtocol] = None) -> ExchangeInterface:
    """
    Фабрика с мягкой прокидкой шины событий внутрь брокера (если поддерживается).
    """
    mode = (getattr(cfg, "MODE", "paper") or "paper").lower()
    if mode == "live":
        from .ccxt_exchange import CcxtExchange as Impl
        broker = Impl.from_settings(cfg)
    elif mode == "backtest":
        from .backtest_exchange import BacktestExchange as Impl
        broker = Impl.from_settings(cfg)
    else:
        from .paper_exchange import PaperExchange as Impl
        broker = Impl.from_settings(cfg)

    if hasattr(broker, "set_bus"):
        try:
            broker.set_bus(bus)  # type: ignore[attr-defined]
        except Exception:
            pass
    return broker
