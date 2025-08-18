from __future__ import annotations
import time
from decimal import Decimal
from typing import Dict, Any, Optional

from crypto_ai_bot.core.risk.sizing import (
    compute_qty_for_notional,
    compute_qty_for_notional_market,
)
from crypto_ai_bot.core.use_cases.protective_exits import ensure_protective_exits
from crypto_ai_bot.core.market_specs import quantize_amount
from crypto_ai_bot.core.brokers.symbols import to_ccxt_symbol, symbol_variants


def _long_qty_any(positions_repo, symbol: str) -> float:
    qty = 0.0
    for s in symbol_variants(symbol):
        qty = max(qty, positions_repo.long_qty(s))
    return qty


def _has_long_any(positions_repo, symbol: str) -> bool:
    return _long_qty_any(positions_repo, symbol) > 0.0


def _idem_key(cfg, broker, sym_ccxt: str, side: str) -> str:
    """
    Ключ идемпотентности: привязан к (exchange, mode, symbol, side, time-bucket).
    Защищает от повторной подачи команды BUY/SELL в коротком окне.
    """
    now_ms = int(time.time() * 1000)
    bucket_ms = int(getattr(cfg, "IDEMPOTENCY_BUCKET_MS", 60_000))
    bucket = now_ms // max(1, bucket_ms)
    ex = getattr(broker, "exchange_name", getattr(cfg, "EXCHANGE", "gateio"))
    mode = getattr(cfg, "MODE", "paper")
    return f"order:{ex}:{mode}:{sym_ccxt}:{side}:{bucket}"


def place_order(
    *,
    cfg,
    broker,
    trades_repo,
    positions_repo,
    exits_repo,
    symbol: str,
    side: str,
    idempotency_repo=None,   # NEW: опционально, совместимо со старым кодом
) -> Dict[str, Any]:
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid side"}

    # CCXT-совместимый символ
    sym_ccxt = to_ccxt_symbol(symbol, getattr(broker, "exchange_name", None))

    # Long-only guard
    if side == "sell" and not _has_long_any(positions_repo, symbol):
        return {"accepted": False, "error": "long-only: no position to sell"}

    # ---- идемпотентность: защищаем от «двойного клика» ----
    idem_key = None
    if idempotency_repo is not None:
        try:
            idem_key = _idem_key(cfg, broker, sym_ccxt, side)
            ttl_sec = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 60))
            if not idempotency_repo.claim(idem_key, ttl_seconds=ttl_sec):
                # Уже есть активная попытка. Попробуем найти pending/partial ордер по символу.
                pendings = trades_repo.find_pending_orders(symbol=sym_ccxt, limit=10)
                for p in pendings:
                    if (p.get("side") or "").lower() == side:
                        # Возвращаем информацию о существующей заявке
                        return {
                            "accepted": True,
                            "state": p.get("state", "pending"),
                            "order_id": p.get("order_id"),
                            "expected_price": p.get("price"),
                            "expected_qty": p.get("exp_qty") or p.get("qty"),
                            "duplicate": True,
                        }
                # Если ничего не нашли — говорим явно
                return {"accepted": False, "error": "duplicate"}
        except Exception:
            # Никогда не роняем выполнение из-за идемпотентности
            idem_key = None

    # Цена
    ticker = broker.fetch_ticker(sym_ccxt)
    last_price = float(ticker.get("last") or ticker.get("close") or ticker.get("info", {}).get("last", 0.0))
    if last_price <= 0:
        if idempotency_repo and idem_key:
            try:
                idempotency_repo.commit(idem_key, state="error:no-price")
            except Exception:
                pass
        return {"accepted": False, "error": "no market price"}

    # market-спеки (если доступны у брокера)
    market = broker.get_market(sym_ccxt) if hasattr(broker, "get_market") else None

    # sizing
    if side == "buy":
        if market:
            qty, reason, need = compute_qty_for_notional_market(cfg, side=side, price=last_price, market=market)
            if qty <= 0:
                if idempotency_repo and idem_key:
                    try:
                        idempotency_repo.commit(idem_key, state=f"error:{reason or 'qty=0'}")
                    except Exception:
                        pass
                if reason == "min_amount":
                    return {"accepted": False, "error": "min_amount", "needed_amount": need}
                if reason == "min_notional":
                    return {"accepted": False, "error": "min_notional", "needed_notional": need}
                return {"accepted": False, "error": "qty=0"}
        else:
            qty = compute_qty_for_notional(cfg, side=side, price=last_price)
    else:
        qty = _long_qty_any(positions_repo, symbol)
        if market:
            qty = quantize_amount(qty, market, side="sell")

    if qty <= 0:
        if idempotency_repo and idem_key:
            try:
                idempotency_repo.commit(idem_key, state="error:qty=0")
            except Exception:
                pass
        return {"accepted": False, "error": "qty=0"}

    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))

    # ---- отправляем ордер ----
    if enable_trading:
        try:
            order = broker.create_order(symbol=sym_ccxt, type="market", side=side, amount=qty)
            order_id = str(order.get("id"))
            trades_repo.create_pending_order(symbol=sym_ccxt, side=side, exp_price=last_price, qty=qty, order_id=order_id)
            if idempotency_repo and idem_key:
                try:
                    idempotency_repo.commit(idem_key, state="pending")
                except Exception:
                    pass
            if side == "buy":
                ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=sym_ccxt, entry_price=last_price, position_id=None)
            return {
                "accepted": True,
                "state": "pending",
                "order_id": order_id,
                "expected_price": last_price,
                "expected_qty": qty,
            }
        except Exception as e:
            if idempotency_repo and idem_key:
                try:
                    idempotency_repo.commit(idem_key, state="error:create_order")
                except Exception:
                    pass
            return {"accepted": False, "error": f"broker-error:{e.__class__.__name__}"}

    # ---- paper-режим: эмулируем заполнение ----
    order_id = f"paper-{sym_ccxt}-{int(Decimal(last_price) * 1000)}"
    trades_repo.create_pending_order(symbol=sym_ccxt, side=side, exp_price=last_price, qty=qty, order_id=order_id)
    fee_bps = float(getattr(cfg, "FEE_TAKER_BPS", 10)) / 10_000.0
    fee_amt = last_price * qty * fee_bps
    trades_repo.fill_order(order_id=order_id, executed_price=last_price, executed_qty=qty, fee_amt=fee_amt, fee_ccy="USDT")
    if idempotency_repo and idem_key:
        try:
            idempotency_repo.commit(idem_key, state="filled")
        except Exception:
            pass
    if side == "buy":
        ensure_protective_exits(cfg, exits_repo, positions_repo, symbol=sym_ccxt, entry_price=last_price, position_id=None)
    return {
        "accepted": True,
        "state": "filled",
        "order_id": order_id,
        "executed_price": last_price,
        "executed_qty": qty,
        "fee_amt": fee_amt,
    }
