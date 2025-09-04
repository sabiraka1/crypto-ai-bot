from __future__ import annotations

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
    why: str = ""  # supplemental reason for blockers (logging/auditing)


class TradeDataFetcher:
    """Helper class to fetch trade-related data from storage."""
    
    @staticmethod
    async def recent_trades(storage: Any, symbol: str, n: int) -> list[dict[str, Any]]:
        """Best-effort: returns last N trades if storage provides such API."""
        try:
            repo = getattr(storage, "trades", None)
            if not repo:
                return []
            if hasattr(repo, "last_trades"):
                return list(repo.last_trades(symbol, n) or [])
            if hasattr(repo, "list_recent"):
                return list(repo.list_recent(symbol=symbol, limit=n) or [])
            return []
        except (AttributeError, ValueError):
            _log.debug("_recent_trades_failed", exc_info=True)
            return []

    @staticmethod
    async def daily_pnl_quote(storage: Any, symbol: str) -> Decimal:
        """Best-effort: get today's PnL in quote currency (if storage supports it)."""
        try:
            repo = getattr(storage, "trades", None)
            if not repo:
                return dec("0")
            if hasattr(repo, "daily_pnl_quote"):
                v = repo.daily_pnl_quote(symbol)
                return dec(str(v))
            return dec("0")
        except (AttributeError, ValueError):
            _log.debug("_daily_pnl_quote_failed", exc_info=True)
            return dec("0")

    @staticmethod
    async def balances_series(storage: Any, symbol: str, limit: int = 48) -> list[Decimal]:
        """Best-effort: series of quote balance snapshots for risk metrics."""
        try:
            repo = getattr(storage, "balances", None)
            if not repo:
                return []
            if hasattr(repo, "recent_total_quote"):
                xs = repo.recent_total_quote(symbol=symbol, limit=limit)
                return [dec(str(x)) for x in (xs or [])]
            return []
        except (AttributeError, ValueError):
            _log.debug("_balances_series_failed", exc_info=True)
            return []


class IdempotencyChecker:
    """Handle idempotency checks."""
    
    @staticmethod
    def generate_key(symbol: str, side: str, q_in: Decimal, b_in: Decimal, session: str) -> str:
        """Generate idempotency key."""
        key_payload = f"{symbol}|{side}|{q_in}|{b_in}|{session}"
        # sha1 retained intentionally for compatibility with existing storage key format
        return "po:" + hashlib.sha1(key_payload.encode("utf-8")).hexdigest()  # noqa: S324
    
    @staticmethod
    async def check_duplicate(storage: StoragePort, idem_key: str, ttl_sec: int, sym: str, bus: EventBusPort) -> dict[str, Any] | None:
        """Check if request is duplicate and store if not."""
        try:
            idem = getattr(storage, "idempotency", None)
            idem_repo = idem() if callable(idem) else idem  # support factory and instance
            if idem_repo is not None and hasattr(idem_repo, "check_and_store"):
                if not bool(idem_repo.check_and_store(idem_key, ttl_sec)):
                    # Duplicate request (drop)
                    await bus.publish(events_topics.TRADE_BLOCKED, {"symbol": sym, "reason": "duplicate"})
                    _log.warning("trade_blocked_duplicate", extra={"symbol": sym})
                    return {"action": "skip", "executed": False, "reason": "duplicate"}
        except (AttributeError, RuntimeError):
            _log.error("idempotency_check_failed", extra={"symbol": sym}, exc_info=True)
        return None


class RiskChecker:
    """Handle risk-related checks."""
    
    def __init__(self, storage: Any, bus: EventBusPort, settings: Any, cfg: RiskConfig):
        self.storage = storage
        self.bus = bus
        self.settings = settings
        self.cfg = cfg
        self.fetcher = TradeDataFetcher()
    
    async def check_loss_streak(self, sym: str) -> dict[str, Any] | None:
        """Check loss streak rule if enabled."""
        if not getattr(self.settings, "RISK_USE_LOSS_STREAK", 0):
            return None
            
        try:
            from crypto_ai_bot.core.domain.risk.rules.loss_streak import LossStreakRule

            max_streak = int(getattr(self.settings, "RISK_LOSS_STREAK_MAX", 3) or 3)
            lookback = int(getattr(self.settings, "RISK_LOSS_STREAK_LOOKBACK", 10) or 10)
            ls_rule = LossStreakRule(max_streak=max_streak, lookback_trades=lookback)
            trades = await self.fetcher.recent_trades(self.storage, sym, n=max(lookback, 10))
            allowed, reason = ls_rule.check(trades)
            if not allowed:
                await self.bus.publish(
                    events_topics.BUDGET_EXCEEDED,
                    {"symbol": sym, "type": "loss_streak", "reason": reason},
                )
                _log.warning("trade_blocked_loss_streak", extra={"symbol": sym, "reason": reason})
                return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
        except ImportError:
            _log.debug("loss_streak_rule_not_available")
        return None
    
    async def check_max_drawdown(self, sym: str) -> dict[str, Any] | None:
        """Check max drawdown rule if enabled."""
        if not getattr(self.settings, "RISK_USE_MAX_DRAWDOWN", 0):
            return None
            
        try:
            from crypto_ai_bot.core.domain.risk.rules.max_drawdown import MaxDrawdownRule

            max_dd = dec(str(getattr(self.settings, "RISK_MAX_DRAWDOWN_PCT", "10.0") or "10.0"))
            max_daily = dec(str(getattr(self.settings, "RISK_MAX_DAILY_LOSS_QUOTE", "0") or "0"))
            md_rule = MaxDrawdownRule(max_drawdown_pct=max_dd, max_daily_loss_quote=max_daily)

            balances = await self.fetcher.balances_series(
                self.storage, sym, limit=int(getattr(self.settings, "RISK_BALS_LOOKBACK", 48) or 48)
            )
            current = balances[-1] if balances else dec("0")
            peak = max(balances) if balances else dec("0")
            daily_pnl = await self.fetcher.daily_pnl_quote(self.storage, sym)

            allowed, reason = md_rule.check(current_balance=current, peak_balance=peak, daily_pnl=daily_pnl)
            if not allowed:
                await self.bus.publish(
                    events_topics.BUDGET_EXCEEDED,
                    {"symbol": sym, "type": "max_drawdown", "reason": reason},
                )
                _log.warning("trade_blocked_max_drawdown", extra={"symbol": sym, "reason": reason})
                return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
        except ImportError:
            _log.debug("max_drawdown_rule_not_available")
        return None
    
    async def check_spread(self, sym: str, broker: BrokerPort) -> dict[str, Any] | None:
        """Check spread limits."""
        try:
            limit_spread = dec(str(getattr(self.cfg, "max_spread_pct", 0.0) or 0))
        except (ValueError, AttributeError):
            _log.debug("spread_limit_parse_failed")
            limit_spread = dec("0")

        if limit_spread <= dec("0"):
            return None
            
        try:
            t = await broker.fetch_ticker(sym)
            bid = dec(str(t.get("bid", "0")) or "0")
            ask = dec(str(t.get("ask", "0")) or "0")
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * dec("100")
                if spread_pct > limit_spread:
                    await self.bus.publish(events_topics.TRADE_BLOCKED, {"symbol": sym, "reason": "spread"})
                    _log.warning(
                        "trade_blocked_spread",
                        extra={
                            "symbol": sym,
                            "spread_pct": f"{spread_pct:.4f}",
                            "limit_pct": str(limit_spread),
                        },
                    )
                    return {
                        "action": "skip",
                        "executed": False,
                        "why": f"blocked: spread {spread_pct:.4f}%>{limit_spread}%",
                    }
        except (ConnectionError, RuntimeError):
            _log.error("spread_check_failed", extra={"symbol": sym}, exc_info=True)
        return None
    
    async def check_rate_limits(self, sym: str) -> dict[str, Any] | None:
        """Check orders per 5 minutes rate limit."""
        if not (getattr(self.cfg, "max_orders_5m", 0) and self.cfg.max_orders_5m > 0):
            return None
            
        try:
            trades_repo = getattr(self.storage, "trades", None)
            if trades_repo and hasattr(trades_repo, "count_orders_last_minutes"):
                recent_count = trades_repo.count_orders_last_minutes(sym, 5)
                if recent_count >= self.cfg.max_orders_5m:
                    await self.bus.publish(
                        events_topics.BUDGET_EXCEEDED,
                        {
                            "symbol": sym,
                            "type": "max_orders_5m",
                            "count_5m": recent_count,
                            "limit": self.cfg.max_orders_5m,
                        },
                    )
                    _log.warning(
                        "trade_blocked_max_orders_5m",
                        extra={"symbol": sym, "count_5m": recent_count, "limit": self.cfg.max_orders_5m},
                    )
                    return {"action": "skip", "executed": False, "why": "blocked: max_orders_5m"}
        except (AttributeError, RuntimeError):
            _log.error("orders_rate_check_failed", extra={"symbol": sym}, exc_info=True)
        return None
    
    async def check_turnover(self, sym: str) -> dict[str, Any] | None:
        """Check turnover cap per day."""
        max_turnover = getattr(self.cfg, "max_turnover_quote_per_day", Decimal("0"))
        try:
            max_turnover = dec(str(max_turnover))
        except (ValueError, AttributeError):
            _log.debug("turnover_limit_parse_failed")
            max_turnover = dec("0")

        if max_turnover <= dec("0"):
            return None
            
        try:
            trades_repo = getattr(self.storage, "trades", None)
            if trades_repo and hasattr(trades_repo, "daily_turnover_quote"):
                current_turnover = trades_repo.daily_turnover_quote(sym)
                if current_turnover >= max_turnover:
                    await self.bus.publish(
                        events_topics.BUDGET_EXCEEDED,
                        {
                            "symbol": sym,
                            "type": "max_turnover_day",
                            "turnover": str(current_turnover),
                            "limit": str(max_turnover),
                        },
                    )
                    _log.warning(
                        "trade_blocked_max_turnover_day",
                        extra={"symbol": sym, "turnover": str(current_turnover), "limit": str(max_turnover)},
                    )
                    return {"action": "skip", "executed": False, "why": "blocked: max_turnover_day"}
        except (AttributeError, RuntimeError):
            _log.error("turnover_check_failed", extra={"symbol": sym}, exc_info=True)
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
    **_kwargs: Any  # Accept but ignore extra kwargs for compatibility
) -> dict[str, Any]:
    """
    Unified path for executing a trade (buy/sell) with idempotency, risk-guards,
    additional pre-flight checks (spread, per-interval rate limits, turnover caps),
    and best-effort recording to storage.
    """

    # --- Canonicalize inputs ---
    sym = canonical(symbol)
    act = (side or "").lower()

    # defaults for amounts
    q_in = _DEFAULT_ZERO if quote_amount is None else dec(str(quote_amount))
    b_in = _DEFAULT_ZERO if base_amount is None else dec(str(base_amount))

    # ---- Idempotency: prevent duplicates ----
    session = getattr(settings, "SESSION_RUN_ID", "") or ""
    idem_key = IdempotencyChecker.generate_key(sym, act, q_in, b_in, session)
    
    result = await IdempotencyChecker.check_duplicate(storage, idem_key, idempotency_ttl_sec, sym, bus)
    if result:
        return result

    # ---- Risk checks ----
    cfg: RiskConfig = (
        risk_manager.cfg if isinstance(risk_manager, RiskManager) else RiskConfig.from_settings(settings)
    )
    
    risk_checker = RiskChecker(storage, bus, settings, cfg)
    
    # Check all risk rules
    for check_method in [
        risk_checker.check_loss_streak,
        risk_checker.check_max_drawdown,
        lambda s: risk_checker.check_spread(s, broker),
        risk_checker.check_rate_limits,
        risk_checker.check_turnover,
    ]:
        result = await check_method(sym)
        if result:
            return result

    # ---- Place order at broker ----
    try:
        client_order_id = idem_key  # reuse idempotency key for client_order_id
        if act == "buy":
            q_amt = q_in if q_in and q_in > dec("0") else dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
            _log.info("execute_order_buy", extra={"symbol": sym, "quote_amount": str(q_amt)})
            order = await broker.create_market_buy_quote(
                symbol=sym, quote_amount=q_amt, client_order_id=client_order_id
            )
        elif act == "sell":
            b_amt = b_in if b_in and b_in > dec("0") else dec("0")
            _log.info("execute_order_sell", extra={"symbol": sym, "base_amount": str(b_amt)})
            order = await broker.create_market_sell_base(
                symbol=sym, base_amount=b_amt, client_order_id=client_order_id
            )
        else:
            return {"action": "skip", "executed": False, "reason": "invalid_side"}
    except (ConnectionError, RuntimeError) as exc:
        _log.error("execute_trade_failed", extra={"symbol": sym, "side": act}, exc_info=True)
        try:
            await bus.publish(events_topics.TRADE_FAILED, {"symbol": sym, "side": act, "error": str(exc)})
        except (ConnectionError, RuntimeError):
            _log.error("publish_trade_failed_event_failed", extra={"symbol": sym}, exc_info=True)
        return {"action": act, "executed": False, "reason": "broker_exception"}

    # ---- Persist to storage (best-effort) ----
    await _persist_order(storage, sym, order)

    # ---- Publish execution event ----
    await _publish_completion(bus, sym, act, order)

    return {"action": act, "executed": True, "order": order}


async def _persist_order(storage: Any, sym: str, order: Any) -> None:
    """Persist order to storage (best-effort)."""
    try:
        if hasattr(storage, "trades") and hasattr(storage.trades, "add_from_order"):
            storage.trades.add_from_order(order)
    except (AttributeError, RuntimeError):
        _log.error("add_trade_failed", extra={"symbol": sym}, exc_info=True)

    try:
        if hasattr(storage, "orders") and hasattr(storage.orders, "upsert_open"):
            storage.orders.upsert_open(order)
    except (AttributeError, RuntimeError):
        _log.error("upsert_order_failed", extra={"symbol": sym}, exc_info=True)


async def _publish_completion(bus: EventBusPort, sym: str, act: str, order: Any) -> None:
    """Publish trade completion event."""
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
    except (ConnectionError, RuntimeError):
        _log.error("publish_trade_completed_failed", extra={"symbol": sym}, exc_info=True)