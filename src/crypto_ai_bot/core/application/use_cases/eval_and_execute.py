from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("usecase.eval_and_execute")


@dataclass(frozen=True)
class EvalResult:
    decided: bool
    action: str  # "buy" | "sell" | "skip"
    reason: str = ""
    score: str = "0"
    executed: bool = False
    order: Any | None = None


async def _load_strategy_from_settings(settings: Any) -> Any | None:
    """
    Resolve strategy implementation from settings.
    Expected contracts:
      - callable in settings.STRATEGY_IMPL -> returns strategy object with .generate(settings, ctx)
      - default fallback: SignalsPolicyStrategy() from domain if available
    """
    try:
        impl = getattr(settings, "STRATEGY_IMPL", None)
        if impl:
            if callable(impl):
                return impl()
            # string path support could be added here if needed
    except Exception:  # noqa: BLE001
        _log.error("strategy_impl_load_failed", exc_info=True)

    # Fallback to default strategy
    try:
        from crypto_ai_bot.core.domain.strategies.signals_policy_strategy import SignalsPolicyStrategy

        return SignalsPolicyStrategy()
    except Exception:  # noqa: BLE001
        _log.error("default_strategy_import_failed", exc_info=True)
        return None


async def eval_and_execute(
    *,
    symbol: str,
    storage: Any,
    broker: Any,
    bus: Any,
    risk: Any,          # Orchestrator passes RiskManager here
    exits: Any,
    settings: Any,
) -> EvalResult:
    """
    1) Strategy -> decision (generate)
    2) Risk check (no side-effects in domain; events are published here)
    3) Execute trade (and publish execution events)
    """
    try:
        # 1) Strategy decision
        strategy = await _load_strategy_from_settings(settings)
        if not strategy:
            return EvalResult(decided=False, action="skip", reason="strategy_missing")

        try:
            decision = await strategy.generate(settings, {"symbol": symbol})
        except Exception:  # noqa: BLE001
            _log.error(
                "strategy_generate_failed",
                extra={"symbol": symbol, "strategy": getattr(strategy, "name", type(strategy).__name__)},
                exc_info=True,
            )
            return EvalResult(decided=False, action="skip", reason="strategy_error")

        if not isinstance(decision, dict):
            return EvalResult(decided=False, action="skip", reason="invalid_decision")

        action = str(decision.get("action", "skip") or "skip").lower()
        if action not in ("buy", "sell"):
            return EvalResult(decided=False, action="skip", reason=decision.get("reason", "no_action"))

        # 2) Risk check (orchestrator-supplied risk manager)
        ok = True
        why = ""
        try:
            ok, why, _ = risk.check(symbol=symbol, storage=storage)
        except Exception:  # noqa: BLE001
            _log.error("risk_check_failed", extra={"symbol": symbol}, exc_info=True)
            ok = False
            why = "risk_check_exception"

        if not ok:
            try:
                from crypto_ai_bot.core.application import events_topics as EVT

                await bus.publish(EVT.TRADE_BLOCKED, {"symbol": symbol, "reason": why})
            except Exception:  # noqa: BLE001
                _log.error("publish_trade_blocked_failed", extra={"symbol": symbol}, exc_info=True)
            return EvalResult(decided=True, action="skip", reason=why)

        # 3) Execute
        exec_res = await execute_trade(
            symbol=symbol,
            side=action,
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings,
            risk_manager=risk,
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
    except Exception:  # noqa: BLE001
        _log.error("eval_and_execute_failed", extra={"symbol": symbol}, exc_info=True)
        return EvalResult(decided=False, action="skip", reason="eval_execute_exception")
