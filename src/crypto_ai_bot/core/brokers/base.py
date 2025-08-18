from __future__ import annotations
from typing import Any, Optional, Protocol, Dict

class ExchangeInterface(Protocol):
    exchange_name: str
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]: ...
    def create_order(self, *, symbol: str, type: str, side: str, amount: float, price: float|None=None, params: dict|None=None) -> Dict[str, Any]: ...
    def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]: ...
    def get_market(self, symbol: str) -> Dict[str, Any] | None: ...

# Единообразно используем CCXT-адаптер
from .ccxt_impl import CCXTExchange

def create_broker(settings: Any, bus: Optional[Any] = None) -> ExchangeInterface:
    ex_name = getattr(settings, "EXCHANGE", "gateio")
    return CCXTExchange(settings=settings, bus=bus, exchange_name=ex_name)
