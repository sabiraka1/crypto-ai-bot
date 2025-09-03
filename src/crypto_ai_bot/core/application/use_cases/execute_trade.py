from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from typing import Any

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical


_log = get_logger("usecase.execute_trade")

# ĞšĞ¾Ğ½ÑÑ‚Ğ°Ğ½Ñ‚Ñ‹ Ğ´Ğ»Ñ Ğ´ĞµÑ„Ğ¾Ğ»Ñ‚Ğ½Ñ‹Ñ… Ğ·Ğ½Ğ°Ñ‡ĞµĞ½Ğ¸Ğ¹ (Ğ¸Ğ·Ğ±ĞµĞ³Ğ°ĞµĞ¼ Ğ¿Ñ€ĞµĞ´ÑƒĞ¿Ñ€ĞµĞ¶Ğ´ĞµĞ½Ğ¸Ñ B008)
_DEFAULT_ZERO = dec("0")
_DEFAULT_KELLY_CAP = dec("0.5")


@dataclass
class ExecuteTradeResult:
    action: str
    executed: bool
    order: Any | None = None
    reason: str = ""
    why: str = ""  # Ğ´Ğ¾Ğ¿. Ğ¿Ğ¾ÑÑĞ½ĞµĞ½Ğ¸Ğµ (Ğ´Ğ»Ñ Ğ¿Ñ€Ğ¸Ñ‡Ğ¸Ğ½ Ğ±Ğ»Ğ¾ĞºĞ¸Ñ€Ğ¾Ğ²ĞºĞ¸)


async def _recent_trades(storage: Any, symbol: str, n: int) -> list[dict[str, Any]]:
    """Ğ‘ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ğ¾ Ğ´Ğ¾ÑÑ‚Ğ°Ñ‘Ğ¼ Ğ¿Ğ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ğµ N ÑĞ´ĞµĞ»Ğ¾Ğº, ĞµÑĞ»Ğ¸ storage Ğ¿Ğ¾Ğ´Ğ´ĞµÑ€Ğ¶Ğ¸Ğ²Ğ°ĞµÑ‚."""
    try:
        repo = getattr(storage, "trades", None)
        if not repo:
            return []
        if hasattr(repo, "last_trades"):
            return list(repo.last_trades(symbol, n) or [])
        if hasattr(repo, "list_recent"):
            return list(repo.list_recent(symbol=symbol, limit=n) or [])
    except Exception:
        pass
    return []


async def _daily_pnl_quote(storage: Any, symbol: str) -> Decimal:
    """Ğ‘ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ğ¾ Ñ‡Ğ¸Ñ‚Ğ°ĞµĞ¼ Ğ´Ğ½ĞµĞ²Ğ½Ğ¾Ğ¹ PnL Ğ² ĞºĞ¾Ñ‚Ğ¸Ñ€ÑƒĞµĞ¼Ğ¾Ğ¹ Ğ²Ğ°Ğ»ÑÑ‚Ğµ (ĞµÑĞ»Ğ¸ Ğ´Ğ¾ÑÑ‚ÑƒĞ¿Ğ½Ğ¾)."""
    try:
        repo = getattr(storage, "trades", None)
        if not repo:
            return dec("0")
        if hasattr(repo, "daily_pnl_quote"):
            v = repo.daily_pnl_quote(symbol)
            return dec(str(v))
    except Exception:
        return dec("0")
    return dec("0")


async def _balances_series(storage: Any, symbol: str, limit: int = 48) -> list[Decimal]:
    """Ğ˜ÑÑ‚Ğ¾Ñ€Ğ¸Ñ Ğ±Ğ°Ğ»Ğ°Ğ½ÑĞ¾Ğ² Ğ´Ğ»Ñ Ğ¾Ñ†ĞµĞ½ĞºĞ¸ Ğ¿Ñ€Ğ¾ÑĞ°Ğ´ĞºĞ¸ (ĞµÑĞ»Ğ¸ ĞµÑÑ‚ÑŒ Ñ€ĞµĞ¿Ğ¾Ğ·Ğ¸Ñ‚Ğ¾Ñ€Ğ¸Ğ¹ Ğ¼ĞµÑ‚Ñ€Ğ¸Ğº/Ğ±Ğ°Ğ»Ğ°Ğ½ÑĞ¾Ğ²)."""
    try:
        repo = getattr(storage, "balances", None)
        if not repo:
            return []
        if hasattr(repo, "recent_total_quote"):
            xs = repo.recent_total_quote(symbol=symbol, limit=limit)
            return [dec(str(x)) for x in (xs or [])]
    except Exception:
        return []
    return []


async def execute_trade(
    *,
    symbol: str,
    side: str,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    settings: Any,
    exchange: str = "",
    quote_amount: Decimal | None = None,
    base_amount: Decimal | None = None,
    idempotency_bucket_ms: int = 60000,
    idempotency_ttl_sec: int = 3600,
    risk_manager: RiskManager | None = None,
    protective_exits: Any | None = None,
) -> dict[str, Any]:
    """
    Ğ•Ğ´Ğ¸Ğ½Ñ‹Ğ¹ Ğ¿ÑƒÑ‚ÑŒ Ğ¸ÑĞ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ¸Ñ Ñ‚Ğ¾Ñ€Ğ³Ğ¾Ğ²Ğ¾Ğ³Ğ¾ Ñ€ĞµÑˆĞµĞ½Ğ¸Ñ (buy/sell) Ñ ÑƒÑ‡Ñ‘Ñ‚Ğ¾Ğ¼ Ğ¸Ğ´ĞµĞ¼Ğ¿Ğ¾Ñ‚ĞµĞ½Ñ‚Ğ½Ğ¾ÑÑ‚Ğ¸,
    Ñ€Ğ¸ÑĞº-Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğ¹, Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğ¹ Ğ½Ğ° ÑĞ¿Ñ€ĞµĞ´/Ñ‡Ğ°ÑÑ‚Ğ¾Ñ‚Ñƒ/Ğ¾Ğ±Ğ¾Ñ€Ğ¾Ñ‚, Ğ¸ Ğ·Ğ°Ğ¿Ğ¸ÑĞ¸ Ğ² Ñ…Ñ€Ğ°Ğ½Ğ¸Ğ»Ğ¸Ñ‰Ğµ.
    """

    # --- ĞºĞ°Ğ½Ğ¾Ğ½Ğ¸Ğ·Ğ¸Ñ€ÑƒĞµĞ¼ Ğ²Ñ…Ğ¾Ğ´Ñ‹ ---
    sym = canonical(symbol)
    act = (side or "").lower()

    # Ğ”ĞµÑ„Ğ¾Ğ»Ñ‚Ñ‹ ÑÑƒĞ¼Ğ¼
    q_in = _DEFAULT_ZERO if quote_amount is None else dec(str(quote_amount))
    b_in = _DEFAULT_ZERO if base_amount is None else dec(str(base_amount))

    # ---- Ğ¸Ğ´ĞµĞ¼Ğ¿Ğ¾Ñ‚ĞµĞ½Ñ‚Ğ½Ğ¾ÑÑ‚ÑŒ: Ğ¿Ñ€Ğ¾Ğ²ĞµÑ€ĞºĞ° Ğ´ÑƒĞ±Ğ»Ğ¸ĞºĞ°Ñ‚Ğ° ----
    session = getattr(settings, "SESSION_RUN_ID", "") or ""
    key_payload = f"{sym}|{act}|{q_in}|{b_in}|{session}"
    idem_key = f"po:{hashlib.sha1(key_payload.encode('utf-8')).hexdigest()}"

    idem_repo = None
    try:
        idem = getattr(storage, "idempotency", None)
        idem_repo = idem() if callable(idem) else idem  # Ğ¿Ğ¾Ğ´Ğ´ĞµÑ€Ğ¶ĞºĞ° Ğ¸ Ñ„Ğ°Ğ±Ñ€Ğ¸ĞºĞ¸, Ğ¸ Ğ¸Ğ½ÑÑ‚Ğ°Ğ½ÑĞ°
        if idem_repo is not None and hasattr(idem_repo, "check_and_store"):
            if not bool(idem_repo.check_and_store(idem_key, idempotency_ttl_sec)):
                # Ğ£Ğ¶Ğµ ĞµÑÑ‚ÑŒ Ñ‚Ğ°ĞºĞ¾Ğµ Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ (Ğ´ÑƒĞ±Ğ»Ğ¸ĞºĞ°Ñ‚)
                await bus.publish(EVT.TRADE_BLOCKED, {"symbol": sym, "reason": "duplicate"})
                _log.warning("trade_blocked_duplicate", extra={"symbol": sym})
                return {"action": "skip", "executed": False, "reason": "duplicate"}
    except Exception:
        _log.error("idempotency_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ñ€Ğ¸ÑĞº-Ğ¼ĞµĞ½ĞµĞ´Ğ¶ĞµÑ€: ĞºĞ¾Ğ½Ñ„Ğ¸Ğ³ ----
    cfg: RiskConfig = (risk_manager.cfg if isinstance(risk_manager, RiskManager)
                       else RiskConfig.from_settings(settings))

    # ---- (Ğ¾Ğ¿Ñ†Ğ¸Ğ¾Ğ½Ğ°Ğ»ÑŒĞ½Ğ¾) Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ¾: ÑĞµÑ€Ğ¸Ñ ÑƒĞ±Ñ‹Ñ‚Ğ¾Ñ‡Ğ½Ñ‹Ñ… ÑĞ´ĞµĞ»Ğ¾Ğº ----
    try:
        if getattr(settings, "RISK_USE_LOSS_STREAK", 0):
            try:
                from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule
                max_streak = int(getattr(settings, "RISK_LOSS_STREAK_MAX", 3) or 3)
                lookback = int(getattr(settings, "RISK_LOSS_STREAK_LOOKBACK", 10) or 10)
                ls_rule = LossStreakRule(max_streak=max_streak, lookback_trades=lookback)
                trades = await _recent_trades(storage, sym, n=max(lookback, 10))
                allowed, reason = ls_rule.check(trades)
                if not allowed:
                    await bus.publish(EVT.BUDGET_EXCEEDED, {"symbol": sym, "type": "loss_streak", "reason": reason})
                    _log.warning("trade_blocked_loss_streak", extra={"symbol": sym, "reason": reason})
                    return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
            except ImportError:
                pass  # Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ¾ Ğ½Ğµ Ğ¿Ğ¾Ğ´ĞºĞ»ÑÑ‡ĞµĞ½Ğ¾
    except Exception:
        _log.error("loss_streak_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- (Ğ¾Ğ¿Ñ†Ğ¸Ğ¾Ğ½Ğ°Ğ»ÑŒĞ½Ğ¾) Ğ¿Ñ€Ğ°Ğ²Ğ¸Ğ»Ğ¾: Ğ¿Ñ€Ğ¾ÑĞ°Ğ´ĞºĞ°/Ğ´Ğ½ĞµĞ²Ğ½Ğ¾Ğ¹ Ğ»Ğ¸Ğ¼Ğ¸Ñ‚ ÑƒĞ±Ñ‹Ñ‚ĞºĞ¾Ğ² ----
    try:
        if getattr(settings, "RISK_USE_MAX_DRAWDOWN", 0):
            try:
                from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule
                max_dd = dec(str(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", "10.0") or "10.0"))
                max_daily = dec(str(getattr(settings, "RISK_MAX_DAILY_LOSS_QUOTE", "0") or "0"))
                md_rule = MaxDrawdownRule(max_drawdown_pct=max_dd, max_daily_loss_quote=max_daily)

                balances = await _balances_series(storage, sym, limit=int(getattr(settings, "RISK_BALS_LOOKBACK", 48) or 48))
                current = balances[-1] if balances else dec("0")
                peak = max(balances) if balances else dec("0")
                daily_pnl = await _daily_pnl_quote(storage, sym)

                allowed, reason = md_rule.check(current_balance=current, peak_balance=peak, daily_pnl=daily_pnl)
                if not allowed:
                    await bus.publish(EVT.BUDGET_EXCEEDED, {"symbol": sym, "type": "max_drawdown", "reason": reason})
                    _log.warning("trade_blocked_max_drawdown", extra={"symbol": sym, "reason": reason})
                    return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
            except ImportError:
                pass
    except Exception:
        _log.error("drawdown_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğµ Ğ½Ğ° ÑĞ¿Ñ€ĞµĞ´ (Ğ¼Ğ°ĞºÑ. Ğ´Ğ¾Ğ¿ÑƒÑÑ‚Ğ¸Ğ¼Ñ‹Ğ¹ ÑĞ¿Ñ€ĞµĞ´ Ğ² %) ----
    try:
        limit_spread = dec(str(getattr(cfg, "max_spread_pct", 0.0) or 0))
    except Exception:
        limit_spread = dec("0")
    if limit_spread > dec("0"):
        try:
            t = await broker.fetch_ticker(sym)
            bid = dec(str(getattr(t, "bid", t.get("bid", "0")) or "0"))
            ask = dec(str(getattr(t, "ask", t.get("ask", "0")) or "0"))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * dec("100")
                if spread_pct > limit_spread:
                    await bus.publish(EVT.TRADE_BLOCKED, {"symbol": sym, "reason": "spread"})
                    _log.warning(
                        "trade_blocked_spread",
                        extra={"symbol": sym, "spread_pct": f"{spread_pct:.4f}", "limit_pct": str(limit_spread)},
                    )
                    return {"action": "skip", "executed": False, "why": f"blocked: spread {spread_pct:.4f}%>{limit_spread}%"}
        except Exception:
            _log.error("spread_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğµ Ñ‡Ğ°ÑÑ‚Ğ¾Ñ‚Ñ‹ Ğ¾Ñ€Ğ´ĞµÑ€Ğ¾Ğ² Ğ·Ğ° 5 Ğ¼Ğ¸Ğ½ÑƒÑ‚ (ĞµÑĞ»Ğ¸ Ğ·Ğ°Ğ´Ğ°Ğ½Ğ¾) ----
    if getattr(cfg, "max_orders_5m", 0) and cfg.max_orders_5m > 0:
        try:
            recent_count = storage.trades.count_orders_last_minutes(sym, 5)
            if recent_count >= cfg.max_orders_5m:
                await bus.publish(
                    EVT.BUDGET_EXCEEDED,
                    {"symbol": sym, "type": "max_orders_5m", "count_5m": recent_count, "limit": cfg.max_orders_5m},
                )
                _log.warning(
                    "trade_blocked_max_orders_5m",
                    extra={"symbol": sym, "count_5m": recent_count, "limit": cfg.max_orders_5m},
                )
                return {"action": "skip", "executed": False, "why": "blocked: max_orders_5m"}
        except Exception:
            _log.error("orders_rate_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ğ¾Ğ³Ñ€Ğ°Ğ½Ğ¸Ñ‡ĞµĞ½Ğ¸Ğµ Ğ´Ğ½ĞµĞ²Ğ½Ğ¾Ğ³Ğ¾ Ğ¾Ğ±Ğ¾Ñ€Ğ¾Ñ‚Ğ° Ğ¿Ğ¾ ĞºĞ¾Ñ‚Ğ¸Ñ€ÑƒĞµĞ¼Ğ¾Ğ¹ (ĞµÑĞ»Ğ¸ Ğ·Ğ°Ğ´Ğ°Ğ½Ğ¾) ----
    max_turnover = getattr(cfg, "max_turnover_quote_per_day", Decimal("0"))
    try:
        max_turnover = dec(str(max_turnover))
    except Exception:
        max_turnover = dec("0")
    if max_turnover > dec("0"):
        try:
            current_turnover = storage.trades.daily_turnover_quote(sym)
            if current_turnover >= max_turnover:
                await bus.publish(
                    EVT.BUDGET_EXCEEDED,
                    {"symbol": sym, "type": "max_turnover_day", "turnover": str(current_turnover), "limit": str(max_turnover)},
                )
                _log.warning(
                    "trade_blocked_max_turnover_day",
                    extra={"symbol": sym, "turnover": str(current_turnover), "limit": str(max_turnover)},
                )
                return {"action": "skip", "executed": False, "why": "blocked: max_turnover_day"}
        except Exception:
            _log.error("turnover_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ğ¸ÑĞ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ¸Ğµ Ğ¾Ñ€Ğ´ĞµÑ€Ğ° Ñ‡ĞµÑ€ĞµĞ· Ğ±Ñ€Ğ¾ĞºĞµÑ€Ğ° ----
    try:
        client_order_id = idem_key  # Ğ¸ÑĞ¿Ğ¾Ğ»ÑŒĞ·ÑƒĞµĞ¼ Ğ¸Ğ´ĞµĞ¼Ğ¿Ğ¾Ñ‚ĞµĞ½Ñ‚Ğ½Ñ‹Ğ¹ ĞºĞ»ÑÑ‡ ĞºĞ°Ğº client_order_id
        if act == "buy":
            q_amt = q_in if q_in and q_in > dec("0") else dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
            _log.info("execute_order_buy", extra={"symbol": sym, "quote_amount": str(q_amt)})
            order = await broker.create_market_buy_quote(symbol=sym, quote_amount=q_amt, client_order_id=client_order_id)
        elif act == "sell":
            b_amt = b_in if b_in and b_in > dec("0") else dec("0")
            _log.info("execute_order_sell", extra={"symbol": sym, "base_amount": str(b_amt)})
            order = await broker.create_market_sell_base(symbol=sym, base_amount=b_amt, client_order_id=client_order_id)
        else:
            return {"action": "skip", "executed": False, "reason": "invalid_side"}
    except Exception:
        _log.error("execute_trade_failed", extra={"symbol": sym, "side": act}, exc_info=True)
        try:
            await bus.publish(EVT.TRADE_FAILED, {"symbol": sym, "side": act, "error": "broker_exception"})
        except Exception:
            _log.error("publish_trade_failed_event_failed", extra={"symbol": sym}, exc_info=True)
        return {"action": act, "executed": False, "reason": "broker_exception"}

    # ---- Ğ·Ğ°Ğ¿Ğ¸ÑÑŒ ÑĞ´ĞµĞ»ĞºĞ¸/Ğ¾Ñ€Ğ´ĞµÑ€Ğ° Ğ² Ñ…Ñ€Ğ°Ğ½Ğ¸Ğ»Ğ¸Ñ‰Ğµ ----
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

    # ---- ÑĞ¾Ğ±Ñ‹Ñ‚Ğ¸Ğµ Ğ¾ Ğ²Ñ‹Ğ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ¸Ğ¸ ÑĞ´ĞµĞ»ĞºĞ¸ (Ğ´Ğ»Ñ settlement/Ğ°Ğ»ĞµÑ€Ñ‚Ğ¾Ğ²) ----
    try:
        await bus.publish(
            EVT.TRADE_COMPLETED,
            {
                "symbol": sym,
                "side": act,
                "order_id": getattr(order, "id", "") or getattr(order, "order_id", ""),
                "amount": str(getattr(order, "amount", "")),
                "price": str(getattr(order, "price", "")),
                "cost": str(getattr(order, "cost", "")),
                "fee_quote": str(getattr(order, "fee_quote", "")),
            },
        )
    except Exception:
        _log.error("publish_trade_completed_failed", extra={"symbol": sym}, exc_info=True)

    return {"action": act, "executed": True, "order": order}
