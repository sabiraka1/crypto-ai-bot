# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations
import os
import time
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    # предпочтительно использовать ваши настройки
    from ..settings import settings as _cfg  # type: ignore
except Exception:
    class _Cfg:
        ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
        FEE_BPS = float(os.getenv("FEE_BPS", "10"))          # 0.10%
        SLIPPAGE_BPS = float(os.getenv("SLIPPAGE_BPS", "5")) # 0.05%
        CLIENT_ORDER_ID_PREFIX = os.getenv("CLIENT_ORDER_ID_PREFIX", "cai")
    _cfg = _Cfg()  # type: ignore

def _apply_slippage(price: float, side: str, bps: float) -> float:
    delta = price * (bps / 10_000.0)
    return price + delta if side.lower() == "buy" else price - delta

def _calc_fee(notional: float, fee_bps: float) -> float:
    return notional * (fee_bps / 10_000.0)

@dataclass
class PlaceOrderResult:
    accepted: bool
    duplicated: bool
    order_id: Optional[str]
    client_order_id: Optional[str]
    executed_price: Optional[float]
    executed_qty: Optional[float]
    fee: float
    reason: Optional[str] = None

async def place_order(
    *,
    uow,
    broker,
    idem_repo,
    trades_repo,
    positions_repo,
    audit_repo,
    risk_manager,
    decision: Dict[str, Any],
    symbol: str,
    side: str,                  # "buy" | "sell"
    qty: float,
    price: Optional[float] = None,
    type_: str = "market",
    now_ts: Optional[float] = None,
) -> PlaceOrderResult:
    """
    Идемпотентность — перед вызовом биржи. При live-режиме вызываем broker.create_order.
    Учитываем комиссии и слиппедж в live-режиме (без изменения вашей логики PnL/учёта).
    """
    now_ts = now_ts or time.time()
    decision_id = (decision.get("id") or "")[:16]
    minute_bucket = int(now_ts // 60)
    idem_key = f"{symbol}:{side}:{qty}:{minute_bucket}:{decision_id}"

    # --- идемпотентность до сети ---
    async with uow:  # зависит от вашей реализации (context manager)
        # поддержка 2 контрактов: check_and_store() или claim()/commit()
        duplicated = False
        if hasattr(idem_repo, "check_and_store"):
            inserted = await idem_repo.check_and_store(idem_key, ttl_seconds=3600)
            duplicated = not bool(inserted)
        elif hasattr(idem_repo, "claim"):
            claim_ok = await idem_repo.claim(idem_key, ttl_seconds=3600)
            duplicated = not bool(claim_ok)
        else:
            # минимальный fallback — не блокируем, но флагуем
            duplicated = False

        if duplicated:
            await audit_repo.append("order_duplicate", {"key": idem_key, "symbol": symbol, "side": side, "qty": qty})
            return PlaceOrderResult(accepted=False, duplicated=True, order_id=None, client_order_id=None, executed_price=None, executed_qty=None, fee=0.0, reason="duplicate")

        # --- риск-правила (ваш менеджер)
        risk_ok, risk_reason = await risk_manager.check(symbol=symbol, side=side, qty=qty, decision=decision)
        if not risk_ok:
            await audit_repo.append("order_rejected_risk", {"symbol": symbol, "side": side, "qty": qty, "reason": risk_reason})
            # освобождение ключа при наличии claim/release
            if hasattr(idem_repo, "release"):
                await idem_repo.release(idem_key)
            return PlaceOrderResult(accepted=False, duplicated=False, order_id=None, client_order_id=None, executed_price=None, executed_qty=None, fee=0.0, reason=risk_reason)

        # --- исполнение ---
        client_oid = f"{getattr(_cfg, 'CLIENT_ORDER_ID_PREFIX', 'cai')}-{minute_bucket}-{decision_id}"
        order_id = None
        executed_price = None
        executed_qty = None
        fee_val = 0.0

        if getattr(_cfg, "ENABLE_TRADING", False):
            # live-path: реальный вызов биржи
            params = {"clientOrderId": client_oid}
            if type_ == "market":
                # рыночный: оценка цены с учётом слиппеджа (для записи в аудит/сделки)
                ticker = await broker.fetch_ticker(symbol)
                base_price = float(ticker.get("last") or ticker.get("close"))
                executed_price = _apply_slippage(base_price, side, getattr(_cfg, "SLIPPAGE_BPS", 0.0))
                executed_qty = float(qty)
                order = await broker.create_order(symbol=symbol, side=side, type_="market", amount=qty, price=None, params=params)
            else:
                # лимитный: цена может быть задана извне; применим "целевой" slippage к лимиту для хранения
                if price is None:
                    raise ValueError("Limit order requires price")
                executed_price = float(_apply_slippage(float(price), side, getattr(_cfg, "SLIPPAGE_BPS", 0.0)))
                executed_qty = float(qty)
                order = await broker.create_order(symbol=symbol, side=side, type_="limit", amount=qty, price=price, params=params)

            order_id = str(order.get("id") or order.get("orderId") or "")
            notional = float(executed_price) * float(executed_qty)
            fee_val = _calc_fee(notional, getattr(_cfg, "FEE_BPS", 0.0))
        else:
            # paper/safe-path: без реального вызова биржи — сохраняем симуляцию (как раньше)
            ticker = await broker.fetch_ticker(symbol)
            base_price = float(ticker.get("last") or ticker.get("close"))
            executed_price = _apply_slippage(base_price if type_ == "market" else (price or base_price), side, getattr(_cfg, "SLIPPAGE_BPS", 0.0))
            executed_qty = float(qty)
            notional = float(executed_price) * float(executed_qty)
            fee_val = _calc_fee(notional, getattr(_cfg, "FEE_BPS", 0.0))
            order_id = None  # симуляция

        # --- запись в хранилища (позиции/сделки/аудит) ---
        await trades_repo.append(symbol=symbol, side=side, qty=executed_qty, price=executed_price, fee=fee_val, decision_id=decision_id, order_id=order_id, client_order_id=client_oid, ts=now_ts)
        await positions_repo.on_trade(symbol=symbol, side=side, qty=executed_qty, price=executed_price, fee=fee_val, decision_id=decision_id, order_id=order_id, ts=now_ts)
        await audit_repo.append("order_placed", {
            "symbol": symbol, "side": side, "qty": executed_qty, "price": executed_price,
            "fee": fee_val, "orderId": order_id, "clientOrderId": client_oid, "decisionId": decision_id, "idemKey": idem_key
        })

        # фиксация ключа идемпотентности
        if hasattr(idem_repo, "commit"):
            await idem_repo.commit(idem_key)

        return PlaceOrderResult(
            accepted=True, duplicated=False, order_id=order_id, client_order_id=client_oid, executed_price=executed_price, executed_qty=executed_qty, fee=fee_val
        )
