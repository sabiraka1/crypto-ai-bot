from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class ExchangeInterface(ABC):
    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]: ...
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200): ...
    @abstractmethod
    def create_order(
        self, symbol: str, side: str, type_: str, amount: float,
        price: Optional[float] = None, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]: ...
    @abstractmethod
    def cancel_order(self, id_: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    @abstractmethod
    def fetch_balance(self) -> Dict[str, Any]: ...

def create_broker(settings, bus=None) -> ExchangeInterface:
    mode = getattr(settings, "MODE", "paper").lower()
    if mode == "live":
        from .ccxt_exchange import CCXTExchange
        return CCXTExchange(settings=settings, bus=bus)
    elif mode == "paper":
        from .paper_exchange import PaperExchange
        return PaperExchange(settings=settings, bus=bus)  # type: ignore
    elif mode == "backtest":
        from .backtest_exchange import BacktestExchange
        return BacktestExchange(settings=settings, bus=bus)  # type: ignore
    raise ValueError(f"Unsupported MODE={mode!r}")
