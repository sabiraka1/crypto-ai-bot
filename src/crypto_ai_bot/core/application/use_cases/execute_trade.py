from __future__ import annotations
# src/crypto_ai_bot/core/application/use_cases/execute_trade.py
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("usecase.execute_trade")

# Константы для дефолтных значений B008
_DEFAULT_ZERO = dec("0")
_DEFAULT_KELLY_CAP = dec("0.5")


@dataclass
class ExecuteTradeResult:
    action: str
    executed: bool
    order: Any | None = None
    reason: str = ""
    why: str = ""  # доп. пояснение (для причин блокировки)


async def _recent_trades(storage: Any, symbol: str, n: int) -> list[Dict[str, Any]]:
    """Безопасно достаём последние N сделок, если storage поддерживает."""
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
    """Безопасно читаем дневной PnL в котируемой валюте (если доступно)."""
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
    """История балансов для оценки просадки (если есть репозиторий метрик/балансов)."""
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
) -> Dict[str, Any]:
    """Исполняет торговое решение (покупку или продажу) с учетом идемпотентности и риск-лимитов."""
    # Обработка дефолтных значений для B008
    if quote_amount is None:
        quote_amount = _DEFAULT_ZERO
    if base_amount is None:
        base_amount = _DEFAULT_ZERO
        
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
                _log.warning("trade_blocked_budget", extra={"symbol": sym, "type": "duplicate"})
                return {"action": "skip", "executed": False, "reason": "duplicate"}
    except Exception:
        _log.error("idempotency_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- риск-менеджер: конфиг ----
    cfg: RiskConfig = risk_manager.config if isinstance(risk_manager, RiskManager) else RiskConfig.from_settings(settings)

    # ---- (опционально) правило: серия убыточных сделок ----
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
                    await bus.publish("budget.exceeded", {"symbol": sym, "type": "loss_streak", "reason": reason})
                    _log.warning("trade_blocked_budget", extra={"symbol": sym, "type": "loss_streak", "reason": reason})
                    return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
            except ImportError:
                pass  # LossStreakRule не найден
    except Exception:
        _log.error("loss_streak_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- (опционально) правило: просадка/дневной лимит убытков ----
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
                    await bus.publish("budget.exceeded", {"symbol": sym, "type": "max_drawdown", "reason": reason})
                    _log.warning("trade_blocked_budget", extra={"symbol": sym, "type": "max_drawdown", "reason": reason})
                    return {"action": "skip", "executed": False, "why": f"blocked: {reason}"}
            except ImportError:
                pass  # MaxDrawdownRule не найден
    except Exception:
        _log.error("drawdown_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- ограничение на спред (макс. допустимый спред в %) ----
    if cfg.max_spread_pct and cfg.max_spread_pct > dec("0"):
        try:
            t = await broker.fetch_ticker(sym)
            bid = dec(str(getattr(t, "bid", t.get("bid", "0")) or "0"))
            ask = dec(str(getattr(t, "ask", t.get("ask", "0")) or "0"))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                if spread_pct > cfg.max_spread_pct:
                    await bus.publish("trade.blocked", {"symbol": sym, "reason": "spread"})
                    _log.warning(
                        "trade_blocked_budget",
                        extra={"symbol": sym, "type": "spread", "spread_pct": f"{spread_pct:.4f}", "limit_pct": str(cfg.max_spread_pct)},
                    )
                    return {"action": "skip", "executed": False, "why": f"blocked: spread {spread_pct:.4f}%>{cfg.max_spread_pct}%"}
        except Exception:
            _log.error("spread_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- ограничение частоты ордеров за 5 минут (если задано) ----
    if cfg.max_orders_5m and cfg.max_orders_5m > 0:
        try:
            recent_count = storage.trades.count_orders_last_minutes(sym, 5)
            if recent_count >= cfg.max_orders_5m:
                await bus.publish("budget.exceeded", {"symbol": sym, "type": "max_orders_5m", "count_5m": recent_count, "limit": cfg.max_orders_5m})
                _log.warning(
                    "trade_blocked_budget",
                    extra={"symbol": sym, "type": "max_orders_5m", "count_5m": recent_count, "limit": cfg.max_orders_5m},
                )
                return {"action": "skip", "executed": False, "why": "blocked: max_orders_5m"}
        except Exception:
            _log.error("orders_rate_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- ограничение дневного оборота по котируемой (если задано) ----
    max_turnover_attr = getattr(cfg, "max_turnover_day", None) or cfg.safety_max_turnover_quote_per_day
    if max_turnover_attr and max_turnover_attr > dec("0"):
        try:
            current_turnover = storage.trades.daily_turnover_quote(sym)
            if current_turnover >= max_turnover_attr:
                await bus.publish(
                    "budget.exceeded",
                    {"symbol": sym, "type": "max_turnover_day", "turnover": str(current_turnover), "limit": str(max_turnover_attr)},
                )
                _log.warning(
                    "trade_blocked_budget",
                    extra={"symbol": sym, "type": "max_turnover_day", "turnover": str(current_turnover), "limit": str(max_turnover_attr)},
                )
                return {"action": "skip", "executed": False, "why": "blocked: max_turnover_day"}
        except Exception:
            _log.error("turnover_check_failed", extra={"symbol": sym}, exc_info=True)

    # ---- исполнение ордера через брокера ----
    try:
        client_id = key  # уникальный идентификатор ордера (идемпотентный ключ)
        if act == "buy":
            q_amt = quote_amount if quote_amount and quote_amount > dec("0") else dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0"))
            _log.info("execute_order_buy", extra={"symbol": sym, "quote_amount": str(q_amt)})
            order = await broker.create_market_buy_quote(symbol=sym, quote_amount=q_amt, client_order_id=client_id)
        elif act == "sell":
            b_amt = base_amount if base_amount and base_amount > dec("0") else dec("0")
            _log.info("execute_order_sell", extra={"symbol": sym, "base_amount": str(b_amt)})
            order = await broker.create_market_sell_base(symbol=sym, base_amount=b_amt, client_order_id=client_id)
        else:
            return {"action": "skip", "executed": False, "reason": "invalid_side"}
    except Exception:
        _log.error("execute_trade_failed", extra={"symbol": sym, "side": act}, exc_info=True)
        try:
            await bus.publish("trade.failed", {"symbol": sym, "side": act, "error": "broker_exception"})
        except Exception:
            _log.error("publish_trade_failed_event_failed", extra={"symbol": sym}, exc_info=True)
        return {"action": act, "executed": False, "reason": "broker_exception"}

    # ---- запись сделки в хранилище + обновление позиции ----
    try:
        storage.trades.add_from_order(order)
    except Exception:
        _log.error("add_trade_failed", extra={"symbol": sym}, exc_info=True)

    # ---- событие о выполнении сделки (для settlement) ----
    try:
        await bus.publish(
            "trade.completed",
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