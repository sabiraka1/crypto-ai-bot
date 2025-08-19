from __future__ import annotations

import binascii
import logging
import re
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional, TypedDict, NotRequired

from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.core.use_cases.protective_exits import ensure_protective_exits
from crypto_ai_bot.utils.idempotency import build_key
from crypto_ai_bot.utils.metrics import inc

logger = logging.getLogger("use_cases.place_order")


class Order(TypedDict, total=False):
    id: str
    symbol: str
    side: str        # "buy" | "sell"
    qty: str
    price: float
    status: str      # "executed" | "rejected" | "failed"
    reason: NotRequired[str]


SAFE_TEXT_RE = re.compile(r"[0-9A-Za-z_.-]+")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _last_ticker(broker: Any, symbol: str) -> Dict[str, float]:
    t = broker.fetch_ticker(symbol) or {}
    return {
        "last": float(t.get("last") or t.get("close") or 0.0),
        "bid": float(t.get("bid") or 0.0),
        "ask": float(t.get("ask") or 0.0),
    }


def _calc_spread_bps(tkr: Dict[str, float]) -> float:
    bid = tkr.get("bid", 0.0)
    ask = tkr.get("ask", 0.0)
    if bid > 0.0 and ask > 0.0:
        mid = 0.5 * (bid + ask)
        return float((ask - bid) / mid * 10_000.0)
    return 0.0


def _get_market_meta(broker: Any, symbol: str) -> Dict[str, Any]:
    try:
        ex = getattr(broker, "ccxt", None) or broker
        markets = getattr(ex, "markets", None)
        if markets and symbol in markets:
            m = markets[symbol] or {}
            prec = (m.get("precision") or {})
            lims = (m.get("limits") or {})
            amt_limits = lims.get("amount") or {}
            return {
                "amount_precision": prec.get("amount"),
                "price_precision": prec.get("price"),
                "amount_min": amt_limits.get("min"),
                "amount_max": amt_limits.get("max"),
                "spot": bool(m.get("spot") is True or str(m.get("type") or "").lower() == "spot"),
            }
    except Exception:
        pass
    return {"amount_precision": None, "price_precision": None, "amount_min": None, "amount_max": None, "spot": True}


def _quantize_amount(side: str, amount: float, amount_precision: Optional[int], amount_min: Optional[float]) -> float:
    out = float(amount or 0.0)
    if amount_precision is not None:
        q = Decimal(1).scaleb(-int(amount_precision))
        dec = Decimal(str(out))
        out = float(dec.quantize(q, rounding=ROUND_DOWN if side == "buy" else ROUND_UP))
    if amount_min is not None and out < float(amount_min or 0.0):
        out = float(amount_min) if side == "buy" else 0.0
    return max(0.0, out)


def _effective_price(last_price: float, slippage_bps: float) -> float:
    return float(last_price) * (1.0 + float(slippage_bps) / 10_000.0)


def _buy_quote_budget(notional_quote: float, fee_bps: float) -> float:
    fee_part = float(notional_quote) * (float(fee_bps) / 10_000.0)
    return max(0.0, float(notional_quote) - fee_part)


def _sell_base_qty_from_positions(positions_repo: Any, symbol: str) -> float:
    try:
        if hasattr(positions_repo, "get_open"):
            rows = positions_repo.get_open() or []
            for r in rows:
                if str(r.get("symbol")) == symbol:
                    return float(r.get("qty") or 0.0)
        if hasattr(positions_repo, "get_qty"):
            return float(positions_repo.get_qty(symbol) or 0.0)
    except Exception:
        pass
    return 0.0


def _gateio_text_from(idem_key: Optional[str]) -> str:
    ts = int(time.time() * 1000)
    body = f"cai{format(ts % 10**9, 'x')}"
    if idem_key:
        import binascii
        h = format(binascii.crc32(idem_key.encode("utf-8")) & 0xFFFF_FFFF, "x")
        body = f"{body}{h}"
    body = body[:28]
    if not SAFE_TEXT_RE.fullmatch(body):
        body = re.sub(r"[^0-9A-Za-z_.-]", ".", body)
        body = body[:28]
    return f"t-{body}"


def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Optional[Any],
    symbol: str,
    side: str,  # 'buy' | 'sell'
    idempotency_repo: Optional[Any] = None,
    now_ms: Optional[int] = None,
    bus: Optional[Any] = None,
) -> Dict[str, Any]:
    ts = int(now_ms or _now_ms())
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    side = str(side or "buy").lower()

    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "unsupported_side", "executed_price": 0.0, "executed_qty": 0.0}

    meta = _get_market_meta(broker, sym)
    if not bool(meta.get("spot", True)):
        return {"accepted": False, "error": "spot_only", "executed_price": 0.0, "executed_qty": 0.0}

    if side == "sell":
        pos_qty = _sell_base_qty_from_positions(positions_repo, sym)
        if pos_qty <= 0.0:
            return {"accepted": False, "error": "no_long_position", "executed_price": 0.0, "executed_qty": 0.0}

    idem_key = None
    if idempotency_repo is not None:
        try:
            bucket_ms = int(getattr(cfg, "IDEMPOTENCY_BUCKET_MS", 5_000))
            idem_key = build_key(symbol=sym, side=side, bucket_ms=bucket_ms, source="order")
            ok = idempotency_repo.check_and_store(idem_key, ttl_seconds=int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 300)))
            if not ok:
                inc("orders_duplicate_total")
                return {"accepted": False, "error": "duplicate_request", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}
        except Exception as e:
            logger.exception("idempotency claim failed: %s", e)

    tkr = _last_ticker(broker, sym)
    last = float(tkr["last"])
    if last <= 0.0:
        return {"accepted": False, "error": "no_price", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}
    spread_bps = _calc_spread_bps(tkr)
    max_spread = float(getattr(cfg, "MAX_SPREAD_BPS", 50.0))
    if spread_bps > max_spread:
        return {"accepted": False, "error": "spread_too_wide", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}

    slippage_bps = float(getattr(cfg, "SLIPPAGE_BPS", 20.0))
    fee_bps = float(getattr(cfg, "TAKER_FEE_BPS", 10.0))
    eff_price = _effective_price(last, slippage_bps)

    executed_price = 0.0
    executed_qty = 0.0

    try:
        params: Dict[str, Any] = {"text": _gateio_text_from(idem_key)}
        limiter = getattr(cfg, "limiter", None) or getattr(broker, "limiter", None)
        if limiter is not None and hasattr(limiter, "try_acquire"):
            if not limiter.try_acquire("orders"):
                return {"accepted": False, "error": "rate_limited", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}

        if side == "buy":
            params["createMarketBuyOrderRequiresPrice"] = False
            notional = float(getattr(cfg, "POSITION_SIZE_USD", getattr(cfg, "POSITION_SIZE", 0.0)) or 0.0)
            if notional <= 0.0:
                return {"accepted": False, "error": "zero_notional", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}
            quote_cost = _buy_quote_budget(notional, fee_bps)
            od = broker.create_order(symbol=sym, type="market", side="buy", amount=float(quote_cost), price=None, params=params)
        else:
            base_qty = _sell_base_qty_from_positions(positions_repo, sym)
            base_qty = _quantize_amount("sell", base_qty, meta.get("amount_precision"), meta.get("amount_min"))
            if base_qty <= 0.0:
                return {"accepted": False, "error": "zero_amount", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}
            od = broker.create_order(symbol=sym, type="market", side="sell", amount=float(base_qty), price=None, params=params)

        executed_price = float(od.get("price") or last or 0.0)
        executed_qty = float(od.get("amount") or od.get("filled") or 0.0)

    except Exception as e:
        inc("orders_fail_total")
        logger.exception("broker.create_order failed: %s", e)
        if bus is not None and hasattr(bus, "publish"):
            import asyncio
            asyncio.create_task(bus.publish({
                "type": "OrderExecuted",
                "symbol": sym,
                "order_id": "",
                "side": side,
                "qty": "0",
                "price": 0.0,
                "ts_ms": ts,
                "error": "broker_error",
            }))
        return {"accepted": False, "error": "broker_error", "idempotency_key": idem_key, "executed_price": 0.0, "executed_qty": 0.0}

    try:
        payload = {
            "ts": ts,
            "symbol": sym,
            "side": side,
            "price": executed_price,
            "qty": executed_qty,
            "info": {"idempotency_key": idem_key, "client_order_id": params.get("text"), "exchange_order": od},
        }
        for meth in ("record", "insert", "add", "create"):
            if hasattr(trades_repo, meth):
                getattr(trades_repo, meth)(payload)
                break
    except Exception as e:
        logger.debug("trade persistence failed (non-fatal): %r", e)

    if idempotency_repo is not None and idem_key:
        try:
            idempotency_repo.commit(idem_key)
        except Exception as e:
            logger.debug("idempotency commit failed (non-fatal): %r", e)

    # ✅ единый источник SL/TP: use-case ensure_protective_exits
    try:
        if exits_repo and side == "buy":
            ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=sym, entry_price=executed_price, position_id=None)
    except Exception as e:
        logger.debug("ensure_protective_exits failed (non-fatal): %r", e)

    inc("orders_success_total")
    if bus is not None and hasattr(bus, "publish"):
        import asyncio
        asyncio.create_task(bus.publish({
            "type": "OrderExecuted",
            "symbol": sym,
            "order_id": str(od.get("id") or ""),
            "side": side,
            "qty": str(executed_qty),
            "price": float(executed_price),
            "ts_ms": ts,
        }))

    return {"accepted": True, "executed_price": executed_price, "executed_qty": executed_qty, "idempotency_key": idem_key}
