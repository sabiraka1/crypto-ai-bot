from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from ..brokers.base import IBroker
from ..brokers.symbols import parse_symbol
from ...utils.decimal import dec

@dataclass
class MarketContext:
    symbol: str
    base: str
    quote: str
    last: Decimal
    bid: Decimal
    ask: Decimal

async def build_market_context(
    *, broker: IBroker, symbol: str, price_cache: Optional[Dict[str, Decimal]] = None
) -> MarketContext:
    """Строит рыночный контекст без глобального состояния. При необходимости принимает внешний кэш."""
    t = await broker.fetch_ticker(symbol)
    last = dec(t.last)
    bid = dec(t.bid or last)
    ask = dec(t.ask or last)
    if price_cache is not None:
        price_cache[symbol] = last
    s = parse_symbol(symbol)
    return MarketContext(symbol=symbol, base=s.base, quote=s.quote, last=last, bid=bid, ask=ask)
