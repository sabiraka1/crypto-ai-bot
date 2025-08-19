# src/crypto_ai_bot/core/brokers/base.py
from __future__ import annotations
from typing import Any, Protocol, List, Optional, Dict


class ExchangeInterface(Protocol):
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]: ...
    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def create_order(
        self, symbol: str, type: str, side: str, amount: float,
        price: Optional[float] = None, params: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> Dict[str, Any]: ...
    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
    def fetch_open_orders(
        self, symbol: Optional[str] = None, since: Optional[int] = None,
        limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]: ...


def create_broker(settings: Any, bus: Any = None) -> ExchangeInterface:
    mode = str(getattr(settings, "MODE", "paper")).lower()
    exch = getattr(settings, "EXCHANGE", "binance")

    if mode == "backtest":
        from .backtest_exchange import BacktestExchange
        # единая сигнатура: settings+bus+exchange_name
        return BacktestExchange(settings=settings, bus=bus, exchange_name="backtest")

    from .ccxt_exchange import CCXTExchange
    return CCXTExchange(settings=settings, bus=bus, exchange_name=exch)
