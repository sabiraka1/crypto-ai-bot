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
    # ✅ Исправлено: конвертируем float в Decimal перед вычислениями
    bid_dec = Decimal(str(bid)) if not isinstance(bid, Decimal) else bid
    ask_dec = Decimal(str(ask)) if not isinstance(ask, Decimal) else ask
    last_dec = Decimal(str(last)) if not isinstance(last, Decimal) else last
    
    mid = (bid_dec + ask_dec) / Decimal("2") if (bid_dec > 0 and ask_dec > 0) else last_dec
    spread_pct = ((ask_dec - bid_dec) / mid) * Decimal("100") if mid > 0 else Decimal("0")
    features = {
        "last": str(last_dec),
        "bid": str(bid_dec),
        "ask": str(ask_dec),
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