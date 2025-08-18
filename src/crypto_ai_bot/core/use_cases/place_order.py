# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext
from typing import Any, Dict, Optional
import time

try:
    import ccxt  # type: ignore
    from ccxt.base.errors import (
        DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, NetworkError,
        RequestTimeout, AuthenticationError, PermissionDenied,
        InvalidOrder, InsufficientFunds, OrderNotFound
    )  # type: ignore
except Exception:  # pragma: no cover
    ccxt = None
    DDoSProtection = RateLimitExceeded = ExchangeNotAvailable = NetworkError = RequestTimeout = None  # type: ignore
    AuthenticationError = PermissionDenied = InvalidOrder = InsufficientFunds = OrderNotFound = None  # type: ignore

from crypto_ai_bot.core.risk.rules import (
    risk_concurrent_positions_blocked,
    risk_daily_loss_blocked,
)

getcontext().prec = 28

def _dec(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _market_meta_from_broker(broker: Any, symbol: str) -> Dict[str, Any]:
    try:
        ex = getattr(broker, "ccxt", None)
        if ex is None:
            return {}
        if getattr(ex, "markets", None) is None or not ex.markets:
            ex.load_markets()  # type: ignore[attr-defined]
        m = ex.market(symbol)  # type: ignore[attr-defined]
        out: Dict[str, Any] = {}
        if "limits" in m and m["limits"]:
            lim = m["limits"]
            if lim.get("amount") and lim["amount"].get("min") is not None:
                out["amount_min"] = float(lim["amount"]["min"])
        if "precision" in m and m["precision"]:
            prec = m["precision"]
            if prec.get("amount") is not None:
                out["amount_step"] = float(10 ** (-int(prec["amount"])))
            if prec.get("price") is not None:
                out["price_step"] = float(10 ** (-int(prec["price"])))
        return out
    except Exception:
        return {}

def _round_amount(side: str, amount: Decimal, step: Optional[float]) -> Decimal:
    s = Decimal(str(step if step and step > 0 else 1e-8))
    q = (amount / s).to_integral_value(rounding=ROUND_DOWN if side == "buy" else ROUND_UP)
    return (q * s).normalize()

def _apply_slippage(side: str, price: Decimal, slippage_bps: float) -> Decimal:
    bps = Decimal(str(max(0.0, float(slippage_bps))))
    if bps == 0:
        return price
    if side == "buy":
        return price * (Decimal(1) + bps / Decimal(10_000))
    else:
        return price * (Decimal(1) - bps / Decimal(10_000))

def _taker_fee_amount(notional: Decimal, fee_bps: float) -> Decimal:
    fb = Decimal(str(max(0.0, float(fee_bps))))
    return (notional * fb / Decimal(10_000)).normalize()

def _build_idempotency_key(symbol: str, side: str, bucket_ms: int) -> str:
    return f"{symbol}:{side}:{_now_ms() // int(max(1, bucket_ms))}"

@dataclass
class PlaceOrderResult:
    accepted: bool
    error: Optional[str] = None
    order: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None

def place_order(
    *,
    cfg: Any,
    broker: Any,
    trades_repo: Any,
    positions_repo: Any,
    exits_repo: Any = None,
    symbol: str,
    side: str,
    idempotency_repo: Any = None,
    price: Optional[float] = None,
    amount: Optional[float] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    side = str(side or "").lower().strip()
    if side not in ("buy", "sell"):
        return {"accepted": False, "error": "invalid_args"}

    p = dict(params or {})
    p.setdefault("type", "spot")
    sym = str(symbol)

    # ---- RISK RULES (до идемпотентности) ----
    # 1) лимит на число одновременных позиций (применим только к BUY)
    try:
        max_pos = getattr(cfg, "MAX_CONCURRENT_POSITIONS", None) or getattr(cfg, "MAX_CONCURRENT_TRADES", None)
        if side == "buy" and risk_concurrent_positions_blocked(positions_repo, limit=max_pos):
            return {"accepted": False, "error": "risk_concurrent_limit"}
    except Exception:
        # если репозиторий позиций отвалился — безопаснее блокировать BUY
        if side == "buy":
            return {"accepted": False, "error": "risk_concurrent_repo"}

    # 2) дневной убыток (UTC) — блокируем новые BUY при превышении
    try:
        con = getattr(trades_repo, "con", getattr(cfg, "con", None))
        max_dd = getattr(cfg, "MAX_DAILY_LOSS_USD", None)
        if side == "buy" and con is not None and risk_daily_loss_blocked(con, max_daily_loss_usd=max_dd, symbol=None):
            return {"accepted": False, "error": "risk_daily_loss"}
    except Exception:
        # не блокируем SELL, чтобы можно было уменьшить риск
        if side == "buy":
            return {"accepted": False, "error": "risk_daily_check_failed"}

    # long-only guard для SELL
    try:
        if side == "sell" and hasattr(positions_repo, "has_long") and not positions_repo.has_long(sym):
            return {"accepted": False, "error": "no_position"}
    except Exception:
        return {"accepted": False, "error": "no_position_repo"}

    # ---- идемпотентность ----
    idem_key: Optional[str] = None
    try:
        if idempotency_repo is not None:
            bucket_ms = int(getattr(cfg, "IDEMPOTENCY_BUCKET_MS", 5_000))
            ttl_sec   = int(getattr(cfg, "IDEMPOTENCY_TTL_SEC", 300))
            idem_key = _build_idempotency_key(sym, side, bucket_ms)
            ok = idempotency_repo.check_and_store(idem_key, ttl_seconds=ttl_sec)
            if not ok:
                return {"accepted": False, "error": "duplicate_request", "idempotency_key": idem_key}
    except Exception:
        idem_key = None  # не блокируем из-за репозитория идемпотентности

    # ---- цена и объём ----
    px = _dec(price) if price is not None else None
    if px is None or px <= 0:
        try:
            t = broker.fetch_ticker(sym)
            last = t.get("last") or t.get("close")
            px = _dec(last)
        except Exception as e:
            return {"accepted": False, "error": "ticker_unavailable", "details": repr(e)}
    if px <= 0:
        return {"accepted": False, "error": "invalid_price"}

    amt = _dec(amount) if amount is not None else Decimal(0)
    if amt <= 0:
        notional_usd = _dec(getattr(cfg, "POSITION_SIZE_USD", 0))
        if notional_usd <= 0:
            return {"accepted": False, "error": "position_size_not_set"}
        px_eff_budget = _apply_slippage("buy", px, float(getattr(cfg, "SLIPPAGE_BPS", 0.0)))
        if px_eff_budget <= 0:
            px_eff_budget = px
        amt = (notional_usd / px_eff_budget).normalize()

    meta = _market_meta_from_broker(broker, sym)
    amt = _round_amount(side, amt, meta.get("amount_step"))
    if meta.get("amount_min") and float(amt) < float(meta["amount_min"]):
        return {"accepted": False, "error": "amount_too_small", "amount": float(amt), "min": float(meta["amount_min"])}

    if side == "sell":
        try:
            have = Decimal(str(positions_repo.long_qty(sym)))
        except Exception:
            have = Decimal(0)
        if have <= 0:
            return {"accepted": False, "error": "no_position"}
        if amt > have:
            amt = have

    px_eff = _apply_slippage(side, px, float(getattr(cfg, "SLIPPAGE_BPS", 0.0)))

    # ---- создаём ордер ----
    try:
        order = broker.create_order(
            symbol=sym,
            type="market",
            side=side,
            amount=float(amt),
            price=None,
            params=p,
        )
    except Exception as e:
        code = "exchange_error"
        if RateLimitExceeded and isinstance(e, RateLimitExceeded): code = "rate_limited"  # type: ignore[arg-type]
        elif RequestTimeout and isinstance(e, RequestTimeout): code = "timeout"  # type: ignore[arg-type]
        elif NetworkError and isinstance(e, NetworkError): code = "network_error"  # type: ignore[arg-type]
        elif InvalidOrder and isinstance(e, InvalidOrder): code = "invalid_order"  # type: ignore[arg-type]
        elif InsufficientFunds and isinstance(e, InsufficientFunds): code = "insufficient_funds"  # type: ignore[arg-type]
        elif AuthenticationError and isinstance(e, AuthenticationError): code = "auth_error"  # type: ignore[arg-type]
        elif PermissionDenied and isinstance(e, PermissionDenied): code = "permission_denied"  # type: ignore[arg-type]
        return {"accepted": False, "error": code, "details": repr(e), "idempotency_key": idem_key}

    try:
        executed_price = order.get("price") or float(px_eff)
        executed_qty   = order.get("amount") or float(amt)
        fee_bps = float(getattr(cfg, "FEE_TAKER_BPS", 0.0))
        fee_amt = float(_taker_fee_amount(_dec(executed_price) * _dec(executed_qty), fee_bps))
        row = {
            "symbol": sym, "side": side,
            "price": float(executed_price), "qty": float(executed_qty),
            "fee_amt": fee_amt,
            "state": str(order.get("status") or "filled"),
            "ts": int(order.get("timestamp") or _now_ms()),
            "order_id": str(order.get("id") or ""),
        }
        if hasattr(trades_repo, "insert"):
            trades_repo.insert(row)  # type: ignore[call-arg]
        elif hasattr(trades_repo, "add"):
            trades_repo.add(row)     # type: ignore[call-arg]
        elif hasattr(trades_repo, "record"):
            trades_repo.record(row)  # type: ignore[call-arg]
    except Exception:
        pass

    try:
        if hasattr(positions_repo, "recompute_from_trades"):
            positions_repo.recompute_from_trades(sym)
    except Exception:
        pass

    try:
        if idempotency_repo is not None and idem_key:
            idempotency_repo.commit(idem_key)
    except Exception:
        pass

    return {
        "accepted": True,
        "order": {
            "id": order.get("id"),
            "status": order.get("status") or "filled",
            "executed_price": float(order.get("price") or px_eff),
            "executed_qty": float(order.get("amount") or amt),
        },
        "idempotency_key": idem_key,
    }
