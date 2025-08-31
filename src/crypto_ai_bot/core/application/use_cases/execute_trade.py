﻿from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import StoragePort, BrokerPort, EventBusPort
from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("usecase.execute_trade")


@dataclass
class ExecuteTradeResult:
    action: str
    executed: bool
    order: Optional[Any] = None
    reason: str = ""
    why: str = ""  # доп. пояснение (для причин блокировки)


async def execute_trade(
    *,
    symbol: str,
    side: str,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
    exchange: str = "",
    quote_amount: Decimal = dec("0"),
    base_amount: Decimal = dec("0"),
    idempotency_bucket_ms: int = 60000,
    idempotency_ttl_sec: int = 3600,
    risk_manager: Optional[RiskManager] = None,
    protective_exits: Optional[Any] = None,
) -> dict:
    """Исполняет торговое решение (покупку или продажу) с учетом идемпотентности и риск-лимитов."""
    sym = symbol
    act = side.lower()

    # ---- идемпотентность: проверка дубликата ----
    key_payload = f"{symbol}|{side}|{quote_amount}|{base_amount}|{getattr(settings, 'SESSION_RUN_ID', '') or ''}"
    key = f"po:{hashlib.sha1(key_payload.encode('utf-8')).hexdigest()}"
    idem = getattr(storage, "idempotency", None)
    idem_repo = idem() if callable(idem) else None
    try:
        if idem_repo is not None:
            if not bool(idem_repo.check_and_store(key, idempotency_ttl_sec)):
                # Уже есть такое решение (дубликат)
                await bus.publish("trade.blocked", {"symbol": sym, "reason": "duplicate"})
                _log.warning("execute_blocked_idempotent", extra={"key": key})
                return {"action": "skip", "executed": False, "reason": "duplicate"}
    except Exception as e:
        _log.error("idempotency_check_failed", extra={"error": str(e)})

    # ---- риск-менеджер: лимиты и спред ----
    # Берём конфиг из RM, либо строим из Settings (fallback для совместимости)
    cfg: RiskConfig = risk_manager.config if isinstance(risk_manager, RiskManager) else RiskConfig.from_settings(settings)

    # 1) Ограничение на спред (макс. допустимый спред в %)
    if cfg.max_spread_pct and cfg.max_spread_pct > dec("0"):
        try:
            t = await broker.fetch_ticker(sym)
            bid = dec(str(getattr(t, "bid", t.get("bid", "0")) or "0"))
            ask = dec(str(getattr(t, "ask", t.get("ask", "0")) or "0"))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                if spread_pct > cfg.max_spread_pct:
                    reason = f"spread_exceeds:{spread_pct:.4f}%>{cfg.max_spread_pct}%"
                    await bus.publish("trade.blocked", {"symbol": sym, "reason": "spread"})
                    _log.warning("execute_blocked_spread", extra={"spread_pct": f"{spread_pct:.4f}"})
                    return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
        except Exception as exc:
            _log.error("spread_check_failed", extra={"error": str(exc)})

    # 2) Ограничение частоты ордеров за 5 минут (если задано)
    if cfg.max_orders_5m and cfg.max_orders_5m > 0:
        recent_count = storage.trades.count_orders_last_minutes(sym, 5)
        if recent_count >= cfg.max_orders_5m:
            await bus.publish("budget.exceeded", {"symbol": sym, "type": "max_orders_5m", "count_5m": recent_count, "limit": cfg.max_orders_5m})
            _log.warning("execute_blocked_max_orders", extra={"count_5m": recent_count})
            return {"action": "skip", "executed": False, "why": "blocked: max_orders_5m"}

    # 3) Ограничение дневного оборота по котируемой (если задано)
    if cfg.max_turnover_day and cfg.max_turnover_day > dec("0"):
        current_turnover = storage.trades.daily_turnover_quote(sym)
        if current_turnover >= cfg.max_turnover_day:
            await bus.publish("budget.exceeded", {"symbol": sym, "type": "max_turnover_day", "turnover": str(current_turnover), "limit": str(cfg.max_turnover_day)})
            _log.warning("execute_blocked_max_turnover", extra={"turnover": str(current_turnover)})
            return {"action": "skip", "executed": False, "why": "blocked: max_turnover_day"}

    # ---- исполнение ордера через брокера ----
    try:
        client_id = key  # уникальный идентификатор ордера (идемпотентный ключ)
        if act == "buy":
            q_amt = quote_amount if quote_amount and quote_amount > dec("0") else dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
            _log.info(f"execute_order_buy {sym} q={q_amt}")
            order = await broker.create_market_buy_quote(symbol=sym, quote_amount=q_amt, client_order_id=client_id)
        elif act == "sell":
            b_amt = base_amount if base_amount and base_amount > dec("0") else dec("0")
            _log.info(f"execute_order_sell {sym} b={b_amt}")
            order = await broker.create_market_sell_base(symbol=sym, base_amount=b_amt, client_order_id=client_id)
        else:
            return {"action": "skip", "executed": False, "reason": "invalid_side"}
    except Exception as exc:
        _log.error("execute_trade_failed", extra={"symbol": sym, "side": act, "error": str(exc)})
        await bus.publish("trade.failed", {"symbol": sym, "side": act, "error": str(exc)})
        return {"action": act, "executed": False, "reason": "broker_exception"}

    # ---- запись сделки в хранилище + обновление позиции ----
    try:
        storage.trades.add_from_order(order)
    except Exception as exc:
        _log.error("add_trade_failed", extra={"symbol": sym, "error": str(exc)})

    # ---- событие о выполнении сделки (для settlement) ----
    try:
        await bus.publish("trade.completed", {
            "symbol": sym,
            "side": act,
            "order_id": getattr(order, "id", "") or getattr(order, "order_id", ""),
            "amount": str(getattr(order, "amount", "")),
            "price": str(getattr(order, "price", "")),
            "cost": str(getattr(order, "cost", "")),
            "fee_quote": str(getattr(order, "fee_quote", "")),
        })
    except Exception as exc:
        _log.error("publish_trade_completed_failed", extra={"error": str(exc)})

    return {"action": act, "executed": True, "order": order}
