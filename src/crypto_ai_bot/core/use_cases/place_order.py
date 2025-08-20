# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional

Number = float  # hint alias


def _now_ms() -> int:
    return int(time.time() * 1000)


def _spread_bps(ticker: Dict[str, Any]) -> float:
    bid = float(ticker.get("bid") or 0) or 0.0
    ask = float(ticker.get("ask") or 0) or 0.0
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (ask + bid) / 2.0
        return ((ask - bid) / mid) * 10_000.0
    return 0.0


def _last_price(ticker: Dict[str, Any]) -> float:
    last = ticker.get("last")
    if last is None:
        bid = ticker.get("bid") or 0
        ask = ticker.get("ask") or 0
        if bid and ask:
            return (float(bid) + float(ask)) / 2.0
        return float(ticker.get("close") or 0) or float(ticker.get("ask") or 0) or float(ticker.get("bid") or 0) or 0.0
    return float(last)


def _effective_price(last_px: Number, slippage_bps: Number) -> float:
    return float(last_px) * (1.0 + float(slippage_bps) / 10_000.0)


def _quote_after_fee(notional_quote: Number, fee_bps: Number) -> float:
    """Reduce BUY notional by taker fee so gate.io market BUY passes."""
    fee = float(fee_bps) / 10_000.0
    return max(0.0, float(notional_quote) * (1.0 - fee))


def _make_idem_key(symbol: str, side: str, ttl_sec: int) -> str:
    bucket = _now_ms() // max(1, int(ttl_sec)) // 1000  # seconds bucket
    return f"order:{symbol}:{side}:{bucket}"


def _positions_qty(positions_repo: Any, symbol: str) -> float:
    """Best-effort read of current position qty from repository."""
    if positions_repo is None:
        return 0.0
    # try common APIs
    if hasattr(positions_repo, "get"):
        row = positions_repo.get(symbol)
        if row:
            q = row.get("qty") or row.get("quantity")
            if q is not None:
                return float(q)
    if hasattr(positions_repo, "get_qty"):
        try:
            return float(positions_repo.get_qty(symbol))
        except Exception:
            pass
    # fallback
    return 0.0


def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Any,
    symbol: str,
    side: str,
    idempotency_repo: Any,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Single entry point to place a SPOT **market** order.

    - Long-only: side ∈ {"buy","sell"}; SELL uses current position qty.
    - Idempotency (app level): key reserved in idempotency_repo (TTL bucket).
    - Idempotency (exchange level): key is forwarded to broker via params["idempotency_key"];
      broker will derive clientOrderId / Gate.io `text` from it.
    - Spread guard & fee/slippage-aware sizing.
    """
    sym = str(symbol)
    side = str(side).lower().strip()
    assert side in {"buy", "sell"}, f"unsupported side: {side}"

    if not getattr(cfg, "ENABLE_TRADING", True):
        return {"accepted": False, "code": "trading_disabled"}

    # ---- app-level idempotency
    ttl_sec = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 60))
    idem_key = _make_idem_key(sym, side, ttl_sec=ttl_sec)
    if idempotency_repo is not None and hasattr(idempotency_repo, "check_and_store"):
        ok = bool(idempotency_repo.check_and_store(idem_key, ttl_sec=ttl_sec))
        if not ok:
            return {"accepted": False, "code": "duplicate_request", "idempotency_key": idem_key}

    # ---- market data
    ticker = {}
    try:
        ticker = broker.fetch_ticker(sym) or {}
    except Exception as e:
        return {"accepted": False, "code": "ticker_failed", "error": str(e)}

    # spread guard
    max_spread_bps = float(getattr(cfg, "MAX_SPREAD_BPS", 50.0))
    spr = _spread_bps(ticker)
    if spr > max_spread_bps:
        return {"accepted": False, "code": "spread_too_wide", "spread_bps": spr}

    last_px = _last_price(ticker)
    if last_px <= 0:
        return {"accepted": False, "code": "bad_last_price"}

    # sizing params
    fee_bps = float(getattr(cfg, "FEE_BPS", 20.0))              # 0.20% by default
    slippage_bps = float(getattr(cfg, "SLIPPAGE_BPS", 20.0))    # 0.20% assumed
    eff_px = _effective_price(last_px, slippage_bps)

    params: Dict[str, Any] = {
        "idempotency_key": idem_key,
        # Gate-specific helper for market BUY without price in CCXT:
        "createMarketBuyOrderRequiresPrice": False,
    }

    # ---- determine amount
    if side == "buy":
        # budget (quote) -> amount for gate is *quote cost*, net of fee
        notional = float(getattr(cfg, "POSITION_SIZE_USD", getattr(cfg, "NOTIONAL_USDT", 50.0)))
        quote_cost = _quote_after_fee(notional, fee_bps)
        amount = max(0.0, quote_cost)  # amount is QUOTE
    else:
        # SELL available position (floored to precision by broker)
        pos_qty = _positions_qty(positions_repo, sym)
        if pos_qty <= 0:
            return {"accepted": False, "code": "no_long_position"}
        amount = float(pos_qty)  # amount is BASE

    # ---- optimistic record in trades repo (if API available)
    trade_row_id = None
    ts = _now_ms()
    if trades_repo is not None:
        if hasattr(trades_repo, "create_pending_order"):
            try:
                trade_row_id = trades_repo.create_pending_order(
                    symbol=sym,
                    side=side,
                    price=float(last_px),
                    exp_qty=float(amount if side == "sell" else (amount / eff_px if eff_px > 0 else 0.0)),
                    idempotency_key=idem_key,
                )
            except Exception:
                trade_row_id = None

    # ---- optional pre-check rate limit (soft)
    if hasattr(broker, "limiter") and hasattr(broker.limiter, "try_acquire"):
        bucket = "orders"
        if not broker.limiter.try_acquire(bucket):
            return {"accepted": False, "code": "rate_limited_local"}

    # ---- send order
    try:
        od = broker.create_order(
            symbol=sym,
            type="market",
            side=side,
            amount=float(amount),
            price=None,
            params=params,
        ) or {}
    except Exception as e:
        # rollback idempotency key if we created a pending trade and want re-try
        return {"accepted": False, "code": "order_failed", "error": str(e), "idempotency_key": idem_key}

    # ---- persist exchange response if repo has proper API
    order_id = str(od.get("id") or od.get("order_id") or "")
    avg_px = float(od.get("average") or od.get("price") or 0.0) or eff_px
    filled = float(od.get("filled") or od.get("amount") or 0.0)

    executed_price = float(avg_px or eff_px)
    executed_qty = float(filled if side == "sell" else (filled or (amount / eff_px if eff_px > 0 else 0.0)))

    if trades_repo is not None:
        if hasattr(trades_repo, "record_exchange_update"):
            try:
                trades_repo.record_exchange_update(
                    order_id=order_id,
                    state=str(od.get("status") or "filled"),
                    raw=od,
                )
            except Exception:
                pass
        elif hasattr(trades_repo, "mark_filled") and trade_row_id is not None:
            try:
                trades_repo.mark_filled(trade_row_id, price=executed_price, qty=executed_qty, order_id=order_id)
            except Exception:
                pass

    # ---- publish event (best-effort)
    if bus is not None and hasattr(bus, "publish"):
        try:
            bus.publish({
                "type": "OrderExecuted",
                "symbol": sym,
                "order_id": order_id,
                "side": side,
                "qty": executed_qty,
                "price": executed_price,
                "ts_ms": ts,
            })
        except Exception:
            pass

    return {
        "accepted": True,
        "order": od,
        "executed_price": executed_price,
        "executed_qty": executed_qty,
        "idempotency_key": idem_key,
    }
