from __future__ import annotations

from typing import Any, Dict, Tuple

from ..storage.facade import Storage
from ..strategies.manager import StrategyManager
from ..strategies.base import StrategyContext
from ..brokers.base import TickerDTO


def evaluate_and_store(
    *,
    storage: Storage,
    strategy: StrategyManager,
    symbol: str,
    exchange: str,
    ticker: TickerDTO,
) -> Tuple[str, Dict[str, Any]]:
    ctx: Dict[str, Any] = {
        "ticker": {"last": ticker.last, "bid": ticker.bid, "ask": ticker.ask, "timestamp": ticker.timestamp}
    }
    decision, explain = strategy.decide(symbol=symbol, exchange=exchange, context=ctx, mode="first")
    # сохраняем тикер в нормальную таблицу
    storage.market_data.store_ticker(ticker)
    return decision, explain
