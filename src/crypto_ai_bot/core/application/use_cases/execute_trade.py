from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import hashlib

from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812
from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical


_log = get_logger("usecase.execute_trade")

# сѰ я Ѿѽ ѵ ( ѵѿѵя B008)
_DEFAULT_ZERO = dec("0")
_DEFAULT_KELLY_CAP = dec("0.5")


@dataclass
class ExecuteTradeResult:
    action: str
    executed: bool
    order: Any | None = None
    reason: str = ""
    why: str = ""  # . яс (я ѸѸ Ѿ)


async def _recent_trades(storage: Any, symbol: str, n: int) -> list[dict[str, Any]]:
    """с сѰѼ с N с, с storage Ѷ."""
    try:
        repo = getattr(storage, "trades", None)
        if not repo:
            return []
        if hasattr(repo, "last_trades"):
            return list(repo.last_trades(symbol, n) or [])
        if hasattr(repo, "list_recent"):
            return list(repo.list_recent(symbol=symbol, limit=n) or [])
    except Exception:  # noqa: BLE001
        pass
    return []


async def _daily_pnl_quote(storage: Any, symbol: str) -> Decimal:
    """с ѸѰ  PnL  Ѹѵ юѵ (с сѿ)."""
    try:
        repo = getattr(storage, "trades", None)
        if not repo:
            return dec("0")
        if hasattr(repo, "daily_pnl_quote"):
            v = repo.daily_pnl_quote(symbol)
            return dec(str(v))
    except Exception:  # noqa: BLE001
        return dec("0")
    return dec("0")


async def _balances_series(storage: Any, symbol: str, limit: int = 48) -> list[Decimal]:
    """сѾѸя с я ѵ Ѿс (с с ѵѾѸ Ѹ/с)."""
    try:
        repo = getattr(storage, "balances", None)
        if not repo:
            return []
        if hasattr(repo, "recent_total_quote"):
            xs = repo.recent_total_quote(symbol=symbol, limit=limit)
            return [dec(str(x)) for x in (xs or [])]
    except Exception:  # noqa: BLE001
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
    ѹ  ся Ѿѳ ѵѵя (buy/sell) с Ѿ ѵѽсѸ,
    Ѹс-Ѱѵ, Ѱѵ  сѵ/ѰсѾ/Ѿ,  с  Ѱѵ.
    """

    # --- ѵ Ѿ ---
    sym = canonical(symbol)
    act = (side or "").lower()

    # Ѿ сѼ
    q_in = _DEFAULT_ZERO if quote_amount is None else dec(str(quote_amount))
    b_in = _DEFAULT_ZERO if base_amount is None else dec(str(base_amount))

    # ---- ѵѽс: ѾѺ ѱѰ ----
    session = getattr(settings, "SESSION_RUN_ID", "") or ""
    key_payload = f"{sym}|{act}|{q_in}|{b_in}|{session}"
    idem_key = f"po:{hashlib.sha1(  # noqa: S324key_payload.encode('utf-8')).hexdigest()}"

    idem_repo = None
    try:
        idem = getattr(storage, "idempotency", None)
        idem_repo = idem() if callable(idem) else idem  # Ѷ  ѰѸ,  сѰс
        if idem_repo is not None and hasattr(idem_repo, "check_and_store"):
            if not bool(idem_repo.check_and_store(idem_key, idempotency_ttl_sec)):
                #  с Ѱ ѵѵ (ѱ)
                await bus.publish(EVT.TRADE_BLOCKED, {"symbol": sym, "reason": "duplicate"})
                _log.warning("trade_blocked_duplicate", extra={"symbol": sym})
                return {"action": "skip", "executed": False, "reason": "duplicate"}
    except Exception:  # noqa: BLE001
        _log.error("idempotency_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ѹс-: Ѹ ----
    cfg: RiskConfig = (risk_manager.cfg if isinstance(risk_manager, RiskManager)
                       else RiskConfig.from_settings(settings))

    # ---- (Ѹѽ) Ѱ: сѸя ѱѾѽ с ----
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
                pass  # Ѱ  юѵ
    except Exception:  # noqa: BLE001
        _log.error("loss_streak_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- (Ѹѽ) Ѱ: Ѿс/  ѱѺ ----
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
    except Exception:  # noqa: BLE001
        _log.error("drawdown_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ѱѵ  сѵ (с. сѸѹ сѵ  %) ----
    try:
        limit_spread = dec(str(getattr(cfg, "max_spread_pct", 0.0) or 0))
    except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            _log.error("spread_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ѱѵ ѰсѾ ѴѾ  5  (с ) ----
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
        except Exception:  # noqa: BLE001
            _log.error("orders_rate_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- Ѱѵ  ѾѰ  Ѹѵ (с ) ----
    max_turnover = getattr(cfg, "max_turnover_quote_per_day", Decimal("0"))
    try:
        max_turnover = dec(str(max_turnover))
    except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            _log.error("turnover_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- с ѴѰ ѵѵ ѾѰ ----
    try:
        client_order_id = idem_key  # сѷѵ ѵѽѹ ю  client_order_id
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
    except Exception:  # noqa: BLE001
        _log.error("execute_trade_failed", extra={"symbol": sym, "side": act}, exc_info=True)
        try:
            await bus.publish(EVT.TRADE_FAILED, {"symbol": sym, "side": act, "error": "broker_exception"})
        except Exception:  # noqa: BLE001
            _log.error("publish_trade_failed_event_failed", extra={"symbol": sym}, exc_info=True)
        return {"action": act, "executed": False, "reason": "broker_exception"}

    # ---- с с/ѴѰ  Ѱѵ ----
    try:
        if hasattr(storage, "trades") and hasattr(storage.trades, "add_from_order"):
            storage.trades.add_from_order(order)
    except Exception:  # noqa: BLE001
        _log.error("add_trade_failed", extra={"symbol": sym}, exc_info=True)

    try:
        if hasattr(storage, "orders") and hasattr(storage.orders, "upsert_open"):
            storage.orders.upsert_open(order)
    except Exception:  # noqa: BLE001
        _log.error("upsert_order_failed", extra={"symbol": sym}, exc_info=True)

    # ---- сѸ  ѿ с (я settlement/Ѿ) ----
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
    except Exception:  # noqa: BLE001
        _log.error("publish_trade_completed_failed", extra={"symbol": sym}, exc_info=True)

    return {"action": act, "executed": True, "order": order}
