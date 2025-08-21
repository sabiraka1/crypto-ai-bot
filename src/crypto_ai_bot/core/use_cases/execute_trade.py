from __future__ import annotations
from typing import Any, Dict, Tuple

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order

async def execute_trade(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Any,
    idempotency_repo: Any,
    limiter: Any | None,
    symbol: str,
    external: dict | None,
    bus: Any | None,
    risk_manager: Any | None,
) -> Dict[str, Any]:
    """
    Координация одного шага:
      1) evaluate -> (decision, explain)
      2) (опц.) risk_manager.allow?
      3) place_order (если не заблокировано и не HOLD)
      4) публикация события в bus (если передан)
    Возвращает словарь: {decision, executed, why?, result?, explain}
    """
    decision, explain = await evaluate(
        cfg=cfg, broker=broker, positions_repo=positions_repo,
        symbol=symbol, timeframe=None, external=external,
    )

    ctx = {"symbol": symbol, "explain": explain}
    if risk_manager:
        try:
            ok, reason = await risk_manager.allow(decision, symbol, ctx)  # (bool, str)
        except TypeError:
            # допускаем sync реализацию allow(...)
            ok, reason = risk_manager.allow(decision, symbol, ctx)  # type: ignore
        if not ok:
            if bus and hasattr(bus, "publish"):
                await bus.publish("risk.blocked", {"symbol": symbol, "decision": decision, "reason": reason})
            return {"decision": decision, "executed": False, "why": reason, "explain": explain}

    if str(decision).lower() == "hold":
        if bus and hasattr(bus, "publish"):
            await bus.publish("eval.decision", {"symbol": symbol, "decision": "hold", "explain": explain})
        return {"decision": decision, "executed": False, "why": "hold", "explain": explain}

    side = "buy" if str(decision).lower() == "buy" else "sell"
    amount = float(getattr(cfg, "FIXED_AMOUNT", 0.001) or 0.001)

    res = await place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=exits_repo,
        idempotency_repo=idempotency_repo,
        limiter=limiter,
        symbol=symbol,
        side=side,            # "buy" | "sell"
        type="market",        # "market" | "limit"
        amount=amount,
        price=None,
        external=external,
    )

    if bus and hasattr(bus, "publish"):
        topic = "order.failed" if res.get("skipped") else "order.placed"
        await bus.publish(topic, {"symbol": symbol, "decision": decision, "result": res})

    return {"decision": decision, "executed": not res.get("skipped", False), "result": res, "explain": explain}
