from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.core.application.strategy_manager import StrategyManager
from crypto_ai_bot.core.infrastructure.market_data.ccxt_market_data import CcxtMarketData
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.eval_and_execute")


async def _choose_amounts(*, settings: Any, signal: str, quote_balance: Decimal | None) -> tuple[Decimal, Decimal]:
    """
    Возвращает (quote_amount, base_amount)
    - Для buy: используем FIXED_AMOUNT (если задан), иначе долю свободного quote_balance по STRAT_QUOTE_FRACTION.
    - Для sell: базовый размер вне стратегии — оставляем 0 (пусть sell сигнал означает «готовность к продаже»,
      а конкретное количество задаётся выше по логике/позиции; если есть метод position → можно сюда интегрировать).
    """
    if signal == "buy":
        fixed = dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
        if fixed > 0:
            return fixed, dec("0")
        frac = dec(str(getattr(settings, "STRAT_QUOTE_FRACTION", "0.05") or "0.05"))  # 5% по умолчанию
        qa = (quote_balance or dec("0")) * frac
        return (qa if qa > 0 else dec("0")), dec("0")
    if signal == "sell":
        # базовый размер можно расширить после подключения PositionSizer/позиции
        return dec("0"), dec("0")
    return dec("0"), dec("0")


async def eval_and_execute(
    *,
    symbol: str,
    storage: Any,
    broker: Any,
    bus: Any,
    risk: Any,
    exits: Any,
    settings: Any,
) -> dict:
    """
    Единая точка принятия решения:
    1) Получить сигнал стратегии (через StrategyManager).
    2) Если hold — ничего не делаем.
    3) Если buy/sell — вычислить сумму и делегировать в execute_trade (все лимиты/риски там).
    """
    try:
        md = CcxtMarketData(broker=broker, cache_ttl_sec=float(getattr(settings, "MARKETDATA_CACHE_TTL_S", 30) or 30))
        sm = StrategyManager(md=md, settings=settings)
        sig = await sm.decide(symbol)

        if sig.action not in ("buy", "sell"):
            inc("strategy_hold_total", symbol=symbol, reason=sig.reason or "")
            return {"ok": True, "action": "hold", "reason": sig.reason}

        # Баланс в котируемой валюте (для buy sizing)
        quote_balance: Decimal | None = None
        try:
            bal = await broker.fetch_balance()
            quote_ccy = symbol.split("/")[1]
            if isinstance(bal, dict):
                info = bal.get(quote_ccy, {})
                q = info.get("free") or info.get("total")
                quote_balance = dec(str(q)) if q is not None else None
        except Exception:
            _log.error("fetch_balance_failed", extra={"symbol": symbol}, exc_info=True)

        qa, ba = await _choose_amounts(settings=settings, signal=sig.action, quote_balance=quote_balance)

        res = await execute_trade(
            symbol=symbol,
            side=sig.action,
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings,
            exchange=getattr(settings, "EXCHANGE", ""),
            quote_amount=qa,
            base_amount=ba,
            risk_manager=risk,
            protective_exits=exits,
        )
        return {"ok": True, "action": sig.action, "result": res}
    except Exception as exc:
        _log.error("eval_and_execute_failed", extra={"symbol": symbol}, exc_info=True)
        return {"ok": False, "error": str(exc)}
