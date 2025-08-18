# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..settings import Settings  # cfg тип
from crypto_ai_bot.utils.rate_limit import rate_limit  # ← применяем RL к ордерам


def _apply_slippage(price: float, side: str, bps: float) -> float:
    if not price or not bps:
        return float(price)
    delta = float(price) * (float(bps) / 10_000.0)
    return float(price) + delta if str(side).lower() == "buy" else float(price) - delta

def _calc_fee(notional: float, fee_bps: float) -> float:
    if not notional or not fee_bps:
        return 0.0
    return float(notional) * (float(fee_bps) / 10_000.0)

def _minute_bucket(ts_ms: int) -> int:
    return int((ts_ms // 1000) // 60)


# По умолчанию 10 заявок в минуту (можно переопределить в конфиге)
@rate_limit(max_calls=10, window=60)
def place_order(
    cfg: Settings,
    broker,
    repos,
    *,
    symbol: str,
    side: str,
    qty: float,
    price: Optional[float] = None,
    type_: str = "market",
    decision: Optional[Dict[str, Any]] = None,
    bus=None,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    ts_ms = int(now_ms if now_ms is not None else int(time.time() * 1000))
    decision_id = str((decision or {}).get("id") or (decision or {}).get("uuid") or "")[:32]
    minute_b = _minute_bucket(ts_ms)
    idem_key = f"{symbol}:{side}:{qty}:{minute_b}:{decision_id}"

    fee_bps = float(getattr(cfg, "FEE_BPS", 0.0))
    slippage_bps = float(getattr(cfg, "SLIPPAGE_BPS", 0.0))
    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))
    client_oid_prefix = str(getattr(cfg, "CLIENT_ORDER_ID_PREFIX", "cai"))

    # идемпотентность
    duplicated = False
    try:
        idem = repos.idempotency
        if hasattr(idem, "check_and_store"):
            inserted = bool(idem.check_and_store(idem_key, ttl_seconds=3600))
            duplicated = not inserted
        elif hasattr(idem, "claim"):
            got = bool(idem.claim(idem_key, ttl_seconds=3600))
            duplicated = not got
    except Exception:
        duplicated = False

    if duplicated:
        try:
            repos.audit.append("order_duplicate", {"key": idem_key, "symbol": symbol, "side": side, "qty": qty, "ts_ms": ts_ms})
        except Exception:
            pass
        if bus and hasattr(bus, "publish"):
            try:
                bus.publish({"type": "order.duplicate", "payload": {"key": idem_key, "symbol": symbol, "side": side, "qty": qty, "ts_ms": ts_ms}})
            except Exception:
                pass
        return {"accepted": False, "duplicated": True, "orderId": None, "clientOrderId": None,
                "executed_price": None, "executed_qty": None, "fee": 0.0, "reason": "duplicate"}

    # риск
    try:
        risk_ok = True
        risk_reason = None
        rm = getattr(repos, "risk_manager", None)
        if rm and hasattr(rm, "check"):
            risk_ok, risk_reason = rm.check(symbol=symbol, side=side, qty=qty, decision=decision)
        elif hasattr(cfg, "RISK_MANAGER") and hasattr(cfg.RISK_MANAGER, "check"):
            risk_ok, risk_reason = cfg.RISK_MANAGER.check(symbol=symbol, side=side, qty=qty, decision=decision)  # type: ignore
        if not risk_ok:
            try:
                repos.audit.append("order_rejected_risk", {"symbol": symbol, "side": side, "qty": qty, "reason": risk_reason, "ts_ms": ts_ms})
            except Exception:
                pass
            if hasattr(repos, "idempotency") and hasattr(repos.idempotency, "release"):
                try:
                    repos.idempotency.release(idem_key)
                except Exception:
                    pass
            return {"accepted": False, "duplicated": False, "orderId": None, "clientOrderId": None,
                    "executed_price": None, "executed_qty": None, "fee": 0.0, "reason": str(risk_reason or "risk_rejected")}
    except Exception:
        try:
            repos.audit.append("order_risk_error", {"symbol": symbol, "side": side, "qty": qty, "ts_ms": ts_ms})
        except Exception:
            pass

    # исполнение
    client_oid = f"{client_oid_prefix}-{minute_b}-{decision_id or 'na'}"[:32]
    order_id: Optional[str] = None
    executed_price: Optional[float] = None
    executed_qty: Optional[float] = None

    try:
        tkr = broker.fetch_ticker(symbol)
        base_price = float(tkr.get("last") or tkr.get("close") or tkr.get("bid") or tkr.get("ask") or 0.0)
    except Exception:
        base_price = 0.0

    ref_price = base_price if type_ == "market" else float(price or 0.0)
    executed_price = _apply_slippage(ref_price, side, slippage_bps) if ref_price else None
    executed_qty = float(qty)

    if enable_trading:
        params = {"clientOrderId": client_oid, "text": client_oid}
        try:
            if type_ == "market":
                od = broker.create_order(symbol=symbol, side=side, type_="market", amount=qty, price=None, params=params)
            else:
                if price is None:
                    raise ValueError("Limit order requires price")
                od = broker.create_order(symbol=symbol, side=side, type_="limit", amount=qty, price=float(price), params=params)
            order_id = str(od.get("id") or od.get("orderId") or od.get("clientOrderId") or "")
        except Exception as e:
            try:
                repos.audit.append("order_place_error", {"symbol": symbol, "side": side, "qty": qty, "type": type_, "error": f"{type(e).__name__}: {e}", "ts_ms": ts_ms})
            except Exception:
                pass
            if bus and hasattr(bus, "publish"):
                try:
                    bus.publish({"type": "dlq.error", "payload": {"op": "create_order", "symbol": symbol, "side": side, "error": f"{type(e).__name__}: {e}"}})
                except Exception:
                    pass
            if hasattr(repos, "idempotency") and hasattr(repos.idempotency, "release"):
                try:
                    repos.idempotency.release(idem_key)
                except Exception:
                    pass
            return {"accepted": False, "duplicated": False, "orderId": None, "clientOrderId": client_oid,
                    "executed_price": None, "executed_qty": None, "fee": 0.0, "reason": "create_order_failed"}

    fee_val = _calc_fee(float(executed_price or 0.0) * float(executed_qty or 0.0), fee_bps)

    try:
        if hasattr(repos, "trades") and hasattr(repos.trades, "append"):
            repos.trades.append(
                symbol=symbol, side=side, qty=float(executed_qty or 0.0), price=float(executed_price or 0.0),
                fee=float(fee_val), decision_id=decision_id or None, order_id=order_id, client_order_id=client_oid,
                ts_ms=ts_ms, note="live" if enable_trading else "paper",
            )
        if hasattr(repos, "positions") and hasattr(repos.positions, "on_trade"):
            repos.positions.on_trade(
                symbol=symbol, side=side, qty=float(executed_qty or 0.0), price=float(executed_price or 0.0),
                fee=float(fee_val), decision_id=decision_id or None, order_id=order_id, ts_ms=ts_ms,
            )
        if hasattr(repos, "audit") and hasattr(repos.audit, "append"):
            repos.audit.append("order_placed", {
                "symbol": symbol, "side": side, "qty": float(executed_qty or 0.0), "price": float(executed_price or 0.0),
                "fee": float(fee_val), "orderId": order_id, "clientOrderId": client_oid,
                "decisionId": decision_id or None, "idemKey": idem_key, "ts_ms": ts_ms,
            })
    finally:
        try:
            if hasattr(repos, "idempotency") and hasattr(repos.idempotency, "commit"):
                repos.idempotency.commit(idem_key)
        except Exception:
            pass

    if bus and hasattr(bus, "publish"):
        try:
            bus.publish({
                "type": "order.placed",
                "payload": {
                    "symbol": symbol, "side": side, "qty": float(executed_qty or 0.0),
                    "price": float(executed_price or 0.0), "fee": float(fee_val),
                    "orderId": order_id, "clientOrderId": client_oid, "ts_ms": ts_ms,
                },
            })
        except Exception:
            pass

    return {
        "accepted": True, "duplicated": False, "orderId": order_id, "clientOrderId": client_oid,
        "executed_price": float(executed_price or 0.0), "executed_qty": float(executed_qty or 0.0),
        "fee": float(fee_val), "mode": "live" if enable_trading else "paper",
    }
