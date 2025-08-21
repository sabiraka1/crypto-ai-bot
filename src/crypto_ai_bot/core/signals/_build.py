from __future__ import annotations
from typing import Any, Dict
from crypto_ai_bot.utils.time import now_ms

async def build(
    symbol: str,
    *,
    cfg: Any,
    broker: Any,
    positions_repo: Any | None = None,
    timeframe: str | None = None,
    external: dict | None = None,
    context_provider: Any | None = None,
) -> Dict[str, Any]:
    """
    Минимальный сбор фич:
      - last price из broker.fetch_ticker
      - позиция (если есть метод)
      - market context через провайдер (опционально)
    """
    tk = await broker.fetch_ticker(symbol)
    last = float(tk.get("last") or tk.get("bid") or tk.get("ask") or 0.0)

    pos = None
    if positions_repo and hasattr(positions_repo, "get_position"):
        try:
            pos = positions_repo.get_position(symbol)
        except Exception:
            pos = None

    ctx = context_provider.get_context() if context_provider and hasattr(context_provider, "get_context") else {}

    return {
        "ts_ms": now_ms(),
        "symbol": symbol,
        "price": last,
        "position": pos,
        "context": ctx,
        "tf": timeframe,
        "ext": external or {},
        "ind": {},  # место под индикаторы (EMA/RSI) — добавим позже
    }
