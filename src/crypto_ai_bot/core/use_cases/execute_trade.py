from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from ..brokers.base import IBroker, OrderDTO
from ..events.bus import AsyncEventBus
from ..risk.manager import RiskManager
from ..risk.protective_exits import ProtectiveExits
from ..storage.facade import Storage
from ..strategies.manager import StrategyManager
from ..strategies.base import StrategyContext
from ..brokers.symbols import parse_symbol
from ...utils.logging import get_logger
from ...utils.ids import make_client_order_id
from ...utils.time import now_ms
from .partial_fills import PartialFillHandler

_log = get_logger("usecase.execute")


async def build_market_context(*, broker: IBroker, symbol: str) -> Dict[str, Any]:
    t = await broker.fetch_ticker(symbol)
    spread = float((t.ask - t.bid) / t.last * 100) if t.last and t.ask and t.bid else 0.0
    return {"ticker": {"last": t.last, "bid": t.bid, "ask": t.ask, "timestamp": t.timestamp}, "spread": spread}


async def evaluate(*, manager: StrategyManager, symbol: str, exchange: str, ctx: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    d, e = manager.decide(symbol=symbol, exchange=exchange, context=ctx, mode="first")
    return d, e


def _normalize_risk_result(result: Any) -> Tuple[bool, str]:
    """
    Унифицируем ответ RiskManager:
      - (ok, reason)                     -> (ok, reason)
      - {"allowed": bool, "reasons": []} -> (allowed, ";".join(reasons))
      - {"ok": bool, "reason": str}      -> (ok, reason)
      - None / неожиданное               -> (True, "")
    """
    if result is None:
        return True, ""
    if isinstance(result, tuple) and len(result) >= 1:
        ok = bool(result[0])
        reason = str(result[1]) if len(result) > 1 and result[1] is not None else ""
        return ok, reason
    if isinstance(result, dict):
        if "allowed" in result:
            ok = bool(result.get("allowed"))
            reasons = result.get("reasons") or []
            reason = ";".join(map(str, reasons)) if isinstance(reasons, (list, tuple)) else str(reasons)
            return ok, reason
        if "ok" in result:
            return bool(result.get("ok")), str(result.get("reason") or "")
    return True, ""


async def execute_trade(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: AsyncEventBus,
    exchange: str,
    fixed_quote_amount: Decimal,
    idempotency_bucket_ms: int,
    idempotency_ttl_sec: int,
    force_action: Optional[str] = None,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[ProtectiveExits] = None,
) -> Dict[str, Any]:
    """Полный цикл исполнения одной попытки (совместим с исходником)."""
    # 1) market ctx + decision
    ctx = await build_market_context(broker=broker, symbol=symbol)
    manager = StrategyManager()
    decision, explain = (force_action, {"reason": "forced"}) if force_action else await evaluate(manager=manager, symbol=symbol, exchange=exchange, ctx=ctx)

    # 2) risk checks
    if risk_manager:
        try:
            raw = await risk_manager.check(symbol=symbol, action=decision, evaluation={"ctx": ctx, "explain": explain})
        except TypeError:
            # на случай старой сигнатуры
            raw = await risk_manager.check(symbol=symbol, side=decision, evaluation={"ctx": ctx, "explain": explain})  # type: ignore[call-arg]
        ok, reason = _normalize_risk_result(raw)
        if not ok:
            await bus.publish("trade.blocked", {"symbol": symbol, "reason": reason}, key=symbol)
            return {"executed": False, "why": f"blocked:{reason}"}

    # 3) plac
