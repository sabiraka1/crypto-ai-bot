from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application import events_topics
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger("usecase.execute_trade")

_DEFAULT_ZERO = dec("0")


@dataclass
class ExecuteTradeResult:
    action: str
    executed: bool
    order: Any | None = None
    reason: str = ""
    why: str = ""


class IdempotencyChecker:
    """Idempotency check to avoid duplicate trade execution."""

    @staticmethod
    def generate_key(symbol: str, side: str, q_in: Decimal, b_in: Decimal, session: str) -> str:
        key_payload = f"{symbol}|{side}|{q_in}|{b_in}|{session}"
        return "po:" + hashlib.sha1(key_payload.encode("utf-8")).hexdigest()  # noqa: S324

    @staticmethod
    async def check_duplicate(
        storage: StoragePort, idem_key: str, ttl_sec: int, sym: str, bus: EventBusPort
    ) -> dict[str, Any] | None:
        try:
            idem = getattr(storage, "idempotency", None)
            idem_repo = idem() if callable(idem) else idem
            if idem_repo is not None and hasattr(idem_repo, "check_and_store"):
                if not bool(idem_repo.check_and_store(idem_key, ttl_sec)):
                    await bus.publish(events_topics.TRADE_BLOCKED, {"symbol": sym, "reason": "duplicate"})
                    _log.warning("trade_blocked_duplicate", extra={"symbol": sym})
                    return {"action": "skip", "executed": False, "reason": "duplicate"}
        except Exception:
            _log.error("idempotency_check_failed", extra={"symbol": sym}, exc_info=True)
        return None


async def execute_trade(
    *,
    symbol: str,
    side: str,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
    quote_amount: Decimal | None = None,
    base_amount: Decimal | None = None,
    idempotency_ttl_sec: int = 3600,
    risk_manager: RiskManager | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """
    Unified path for executing a trade with:
      - Idempotency
      - Risk checks (via RiskManager)
      - Broker execution with retries
      - Event publishing & storage persistence
    """

    sym = canonical(symbol)
    act = (side or "").lower()

    q_in = _DEFAULT_ZERO if quote_amount is None else dec(str(quote_amount))
    b_in = _DEFAULT_ZERO if base_amount is None else dec(str(base_amount))

    # --- Idempotency ---
    session = getattr(settings, "SESSION_RUN_ID", "") or ""
    idem_key = IdempotencyChecker.generate_key(sym, act, q_in, b_in, session)
    result = await IdempotencyChecker.check_duplicate(storage, idem_key, idempotency_ttl_sec, sym, bus)
    if result:
        return result

    # --- Risk checks ---
    cfg: RiskConfig = (
        risk_manager.cfg if isinstance(risk_manager, RiskManager) else RiskConfig.from_settings(settings)
    )
    rm = RiskManager(cfg)
    ok, why, extra = rm.check(symbol=sym, storage=storage)
    if not ok:
        await bus.publish(events_topics.TRADE_BLOCKED, {"symbol": sym, "reason": why, **extra})
        _log.warning("trade_blocked", extra={"symbol": sym, "reason": why, **extra})
        return {"action": "skip", "executed": False, "why": f"blocked: {why}"}

    # --- Broker execution with retries ---
    client_order_id = idem_key
    for attempt in range(3):
        try:
            if act == "buy":
                q_amt = q_in if q_in > dec("0") else dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
                order = await broker.create_market_buy_quote(
                    symbol=sym, quote_amount=q_amt, client_order_id=client_order_id
                )
            elif act == "sell":
                b_amt = b_in if b_in > dec("0") else dec("0")
                order = await broker.create_market_sell_base(
                    symbol=sym, base_amount=b_amt, client_order_id=client_order_id
                )
            else:
                return {"action": "skip", "executed": False, "reason": "invalid_side"}

            # Persist and publish on success
            await _persist_order(storage, sym, order)
            await _publish_completion(bus, sym, act, order)
            _log.info("trade_completed", extra={"symbol": sym, "side": act})
            return {"action": act, "executed": True, "order": order}

        except Exception as exc:
            _log.error(
                "trade_failed",
                extra={"symbol": sym, "side": act, "attempt": attempt + 1, "error": str(exc)},
            )
            if attempt == 2:
                await bus.publish(events_topics.TRADE_FAILED, {"symbol": sym, "side": act, "error": str(exc)})
                return {"action": act, "executed": False, "reason": str(exc)}
            await asyncio.sleep(2**attempt)


async def _persist_order(storage: Any, sym: str, order: Any) -> None:
    try:
        if hasattr(storage, "trades") and hasattr(storage.trades, "add_from_order"):
            storage.trades.add_from_order(order)
    except Exception:
        _log.error("add_trade_failed", extra={"symbol": sym}, exc_info=True)

    try:
        if hasattr(storage, "orders") and hasattr(storage.orders, "upsert_open"):
            storage.orders.upsert_open(order)
    except Exception:
        _log.error("upsert_order_failed", extra={"symbol": sym}, exc_info=True)


async def _publish_completion(bus: EventBusPort, sym: str, act: str, order: Any) -> None:
    try:
        order_id = getattr(order, "id", None) or getattr(order, "order_id", "")
        await bus.publish(
            events_topics.TRADE_COMPLETED,
            {
                "symbol": sym,
                "side": act,
                "order_id": str(order_id),
                "amount": str(getattr(order, "amount", "")),
                "price": str(getattr(order, "price", "")),
                "cost": str(getattr(order, "cost", "")),
                "fee_quote": str(getattr(order, "fee_quote", "")),
            },
        )
    except Exception:
        _log.error("publish_trade_completed_failed", extra={"symbol": sym}, exc_info=True)
