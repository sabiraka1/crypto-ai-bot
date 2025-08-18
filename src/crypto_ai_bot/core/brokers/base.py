from __future__ import annotations
from typing import Any, Optional

# Единообразно используем CCXTExchange из ccxt_impl
from .ccxt_impl import CCXTExchange

def create_broker(settings: Any, bus: Optional[Any] = None) -> CCXTExchange:
    """
    Единая фабрика брокера.
    settings.EXCHANGE: 'gateio'|'binance'|... (поддерживает CCXT)
    """
    ex_name = getattr(settings, "EXCHANGE", "gateio")
    return CCXTExchange(settings=settings, bus=bus, exchange_name=ex_name)
