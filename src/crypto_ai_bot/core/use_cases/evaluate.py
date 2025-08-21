## `evaluate.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker, TickerDTO
from ..storage.facade import Storage
from ...utils.metrics import inc
@dataclass(frozen=True)
class EvaluationResult:
    symbol: str
    decision: str  # 'buy' | 'sell' | 'hold'
    score: float
    features: Dict[str, Any]
async def evaluate(symbol: str, *, storage: Storage, broker: IBroker, bus: Optional[AsyncEventBus] = None) -> EvaluationResult:
    """Простая оценка: берём тикер, сохраняем снапшот, считаем пару фич, решение - 'hold'.
    Позже будет расширено блоком signals/policy без изменения интерфейса.
    """
    if bus:
        await bus.publish(topics.EVALUATION_STARTED, {"symbol": symbol}, key=symbol)
    ticker: TickerDTO = await broker.fetch_ticker(symbol)
    storage.market_data.store_ticker(ticker)
    last, bid, ask = ticker.last, ticker.bid, ticker.ask
    mid = (bid + ask) / Decimal("2") if (bid > 0 and ask > 0) else last
    spread_pct = ((ask - bid) / mid) * Decimal("100") if mid > 0 else Decimal("0")
    features = {
        "last": str(last),
        "bid": str(bid),
        "ask": str(ask),
        "mid": str(mid),
        "spread_pct": float(spread_pct),
    }
    result = EvaluationResult(symbol=symbol, decision="hold", score=0.0, features=features)
    if bus:
        await bus.publish(
            topics.DECISION_EVALUATED,
            {"symbol": symbol, "decision": result.decision, "score": result.score, "features": result.features},
            key=symbol,
        )
        inc("eval_done", {"decision": result.decision})
    return result