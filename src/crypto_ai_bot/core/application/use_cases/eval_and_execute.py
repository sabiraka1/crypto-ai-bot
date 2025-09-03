from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.utils.logging import get_logger


_log = get_logger("usecase.eval_and_execute")


@dataclass(frozen=True)
class EvalResult:
    decided: bool
    action: str            # "buy" | "sell" | "skip"
    reason: str = ""
    score: str = "0"
    executed: bool = False
    order: Any | None = None


async def eval_and_execute(
    *,
    symbol: str,
    strategy: Any,
    storage: Any,
    broker: Any,
    bus: Any,
    settings: Any,
    risk_manager: Any,
) -> EvalResult:
    """
    1) Стратегия -> решение
    2) RiskManager -> только возвращает ok/reason (без side-effects)
    3) execute_trade -> исполняем и публикуем события исполнения
    """
    try:
        # 1) Получаем решение стратегии (единый контракт generate -> dict)
        try:
            decision = await strategy.generate(settings, {"symbol": symbol})
        except Exception:
            _log.error("strategy_generate_failed", extra={"symbol": symbol, "strategy": getattr(strategy, "name", type(strategy).__name__)}, exc_info=True)
            return EvalResult(decided=False, action="skip", reason="strategy_error")

        if not isinstance(decision, dict):
            return EvalResult(decided=False, action="skip", reason="invalid_decision")

        action = str(decision.get("action", "skip") or "skip").lower()
        if action not in ("buy", "sell"):
            return EvalResult(decided=False, action="skip", reason=decision.get("reason", "no_action"))

        # 2) Проверка рисков (без публикаций из domain)
        ok = True
        why = ""
        try:
            ok, why, _ = risk_manager.check(symbol=symbol, storage=storage)
        except Exception:
            _log.error("risk_check_failed", extra={"symbol": symbol}, exc_info=True)
            ok = False
            why = "risk_check_exception"

        if not ok:
            # side-effects (события) — обязанность orchestration/use-case уровня, не domain
            try:
                from crypto_ai_bot.core.application import events_topics as EVT
                await bus.publish(EVT.TRADE_BLOCKED, {"symbol": symbol, "reason": why})
            except Exception:
                _log.error("publish_trade_blocked_failed", extra={"symbol": symbol}, exc_info=True)
            return EvalResult(decided=True, action="skip", reason=why)

        # 3) Исполнение
        exec_res = await execute_trade(
            symbol=symbol,
            side=action,
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings,
            risk_manager=risk_manager,
            protective_exits=getattr(settings, "EXITS_ENABLED", 1) and getattr(settings, "EXITS_IMPL", None),
        )

        return EvalResult(
            decided=True,
            action=action,
            reason=exec_res.get("reason", ""),
            executed=bool(exec_res.get("executed", False)),
            order=exec_res.get("order"),
            score=str(decision.get("score", "0")),
        )
    except Exception:
        _log.error("eval_and_execute_failed", extra={"symbol": symbol}, exc_info=True)
        return EvalResult(decided=False, action="skip", reason="eval_execute_exception")
