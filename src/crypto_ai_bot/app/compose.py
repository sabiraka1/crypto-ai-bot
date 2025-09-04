from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands
from crypto_ai_bot.app.subscribers.telegram_alerts import attach_alerts
from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812
from crypto_ai_bot.core.application.monitoring.health_checker import HealthChecker
from crypto_ai_bot.core.application.orchestrator import Orchestrator
from crypto_ai_bot.core.application.ports import SafetySwitchPort
from crypto_ai_bot.core.application.protective_exits import ProtectiveExits
from crypto_ai_bot.core.application.reconciliation.discrepancy_handler import PositionsDiscrepancyHandler
from crypto_ai_bot.core.application.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.application.reconciliation.positions import PositionsReconciler
from crypto_ai_bot.core.application.use_cases.eval_and_execute import EvalAndExecuteUseCase
from crypto_ai_bot.core.application.use_cases.execute_trade import ExecuteTradeUseCase
from crypto_ai_bot.core.domain.risk.manager import RiskConfig, RiskManager
from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus
from crypto_ai_bot.core.infrastructure.events.bus_adapter import UnifiedEventBus
from crypto_ai_bot.core.infrastructure.events.redis_bus import RedisEventBus
from crypto_ai_bot.core.infrastructure.safety.dead_mans_switch import DeadMansSwitch
from crypto_ai_bot.core.infrastructure.storage.facade import StorageFacade
from crypto_ai_bot.core.infrastructure.storage.sqlite_adapter import SQLiteAdapter
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.ids import cid_middleware
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, observe
from crypto_ai_bot.utils.retry import retry_async

_log = get_logger("compose")


@dataclass
class AppWiring:
    settings: Any
    storage: Any
    broker: Any
    bus: Any
    risk: Any
    exits: Any
    orchestrator: Orchestrator
    eval_and_execute: EvalAndExecuteUseCase
    execute_trade: ExecuteTradeUseCase
    health: HealthChecker
    telegram_cmd: TelegramBotCommands
    safety: SafetySwitchPort


# ----------------------------- Bus -----------------------------
def _make_bus(settings: Any) -> UnifiedEventBus:
    url = getattr(settings, "EVENT_BUS_URL", "") or ""
    if url.startswith("redis://"):
        _log.info("event_bus.redis.enabled", extra={"url": url})
        bus: AsyncEventBus = RedisEventBus(url=url)
    else:
        _log.info("event_bus.memory.enabled")
        bus = AsyncEventBus()
    bus.use(cid_middleware())  # attach correlation-id middleware
    return UnifiedEventBus(bus)


# ----------------------------- Storage -----------------------------
def _make_storage(settings: Any) -> StorageFacade:
    path = getattr(settings, "DB_PATH", "app.db")
    _log.info("storage.sqlite", extra={"path": path})
    return StorageFacade(SQLiteAdapter(path))


# ----------------------------- Broker -----------------------------
def _make_broker(settings: Any) -> Any:
    return make_broker(
        exchange=getattr(settings, "EXCHANGE", "gateio"),
        api_key=getattr(settings, "API_KEY", ""),
        secret=getattr(settings, "API_SECRET", ""),
        password=getattr(settings, "API_PASSWORD", None),
        sandbox=bool(getattr(settings, "SANDBOX", False)),
        rate_limit_ms=int(getattr(settings, "RATE_LIMIT_MS", 1000) or 1000),
    )


# ----------------------------- Risk -----------------------------
def _make_risk(settings: Any) -> RiskManager:
    return RiskManager(config=RiskConfig.from_settings(settings))


# ----------------------------- Protective exits -----------------------------
def _make_protective_exits(*, bus: Any, settings: Any) -> ProtectiveExits:
    return ProtectiveExits(
        bus=bus,
        symbol=str(getattr(settings, "SYMBOL", "BTC/USDT")),
        timeframe=str(getattr(settings, "TIMEFRAME", "15m")),
        atr_period=int(getattr(settings, "EXIT_ATR_PERIOD", 14) or 14),
        atr_mult=float(getattr(settings, "EXIT_ATR_MULT", 2.0) or 2.0),
        rsi_period=int(getattr(settings, "EXIT_RSI_PERIOD", 14) or 14),
        rsi_sell=float(getattr(settings, "EXIT_RSI_SELL", 70.0) or 70.0),
        rsi_buy=float(getattr(settings, "EXIT_RSI_BUY", 30.0) or 30.0),
        cooldown_sec=int(getattr(settings, "EXIT_COOLDOWN_SEC", 0) or 0),
    )


# ----------------------------- Health -----------------------------
def _make_health(*, storage: StorageFacade, broker: Any, settings: Any) -> HealthChecker:
    return HealthChecker(
        storage=storage,
        broker=broker,
        symbol=str(getattr(settings, "SYMBOL", "BTC/USDT")),
        timeframe=str(getattr(settings, "TIMEFRAME", "15m")),
        warn_after_sec=int(getattr(settings, "HEALTH_WARN_AFTER_SEC", 120) or 120),
    )


# ----------------------------- Safety (DMS) -----------------------------
def _make_safety(*, bus: UnifiedEventBus, broker: Any, settings: Any) -> DeadMansSwitch:
    symbol = str(getattr(settings, "SYMBOL", "BTC/USDT"))
    warn_drop_pct = float(getattr(settings, "DMS_WARN_DROP_PCT", 2.0) or 2.0)
    trigger_drop_pct = float(getattr(settings, "DMS_TRIGGER_DROP_PCT", 4.0) or 4.0)
    min_price = Decimal(str(getattr(settings, "DMS_MIN_PRICE", 0.0) or 0.0))
    return DeadMansSwitch(
        bus=bus,
        symbol=symbol,
        broker=broker,
        warn_drop_pct=warn_drop_pct,
        trigger_drop_pct=trigger_drop_pct,
        warn_min_price=min_price if min_price > 0 else None,
    )


# ----------------------------- Use-cases -----------------------------
def _make_use_cases(
    *, settings: Any, storage: StorageFacade, broker: Any, bus: UnifiedEventBus, risk: RiskManager
) -> tuple[EvalAndExecuteUseCase, ExecuteTradeUseCase]:
    eval_and_execute = EvalAndExecuteUseCase(
        symbol=str(getattr(settings, "SYMBOL", "BTC/USDT")),
        timeframe=str(getattr(settings, "TIMEFRAME", "15m")),
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        trade_quote=Decimal(str(getattr(settings, "TRADE_AMOUNT", "10") or "10")),
        sl_pct=float(getattr(settings, "SL_PCT", 1.0) or 1.0),
        tp_pct=float(getattr(settings, "TP_PCT", 2.0) or 2.0),
        allow_short=bool(getattr(settings, "ALLOW_SHORT", False)),
    )

    execute_trade = ExecuteTradeUseCase(
        symbol=str(getattr(settings, "SYMBOL", "BTC/USDT")),
        timeframe=str(getattr(settings, "TIMEFRAME", "15m")),
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
    )
    return eval_and_execute, execute_trade


# ----------------------------- Reconciliation -----------------------------
def _make_reconcilers(*, storage: StorageFacade, broker: Any, bus: UnifiedEventBus) -> tuple[Any, Any, Any]:
    po = PositionsReconciler(storage=storage, broker=broker, bus=bus)
    dh = PositionsDiscrepancyHandler(storage=storage, broker=broker, bus=bus)
    orc = OrdersReconciler(storage=storage, broker=broker, bus=bus)
    return po, dh, orc


# ----------------------------- Orchestrator -----------------------------
def _make_orchestrator(
    *,
    settings: Any,
    bus: UnifiedEventBus,
    eval_and_execute: EvalAndExecuteUseCase,
    execute_trade: ExecuteTradeUseCase,
    storage: StorageFacade,
    risk: RiskManager,
    exits: ProtectiveExits,
) -> Orchestrator:
    orch = Orchestrator(bus=bus)

    # Attach periodic loop: evaluate-and-execute
    interval_sec = int(getattr(settings, "LOOP_INTERVAL_SEC", 60) or 60)

    async def _loop_eval() -> None:
        try:
            await eval_and_execute.run_once()
            inc("loop.eval.ok")
        except Exception:
            inc("loop.eval.err")
            _log.exception("loop_eval_failed")

    orch.attach_loop(name="eval", interval_sec=interval_sec, loop=_loop_eval)

    # Attach periodic loop: reconciliation
    recon_interval = int(getattr(settings, "RECONCILE_INTERVAL_SEC", 300) or 300)

    positions_reconciler, discrepancy_handler, orders_reconciler = _make_reconcilers(
        storage=storage, broker=eval_and_execute.broker, bus=bus
    )

    async def _loop_reconcile() -> None:
        try:
            await positions_reconciler.run_once()
            await discrepancy_handler.run_once()
            await orders_reconciler.run_once()
            inc("loop.reconcile.ok")
        except Exception:
            inc("loop.reconcile.err")
            _log.exception("loop_reconcile_failed")

    orch.attach_loop(name="reconcile", interval_sec=recon_interval, loop=_loop_reconcile)

    # Attach listeners
    orch.on(EVT.TRADE_COMPLETED, lambda p: observe("trade.completed", float(p.get("quote", 0.0) or 0.0)))
    orch.on(EVT.TRADE_FAILED, lambda _p: inc("trade.failed"))
    orch.on(EVT.RISK_BLOCKED, lambda _p: inc("risk.blocked"))
    orch.on(EVT.BROKER_ERROR, lambda _p: inc("broker.error"))

    # Attach safety & exits triggers to bus
    # (protective exits publish their own events)
    orch.on(EVT.DMS_TRIGGERED, lambda p: _log.warning("dms_triggered", extra=p))
    orch.on(EVT.DMS_SKIPPED, lambda p: _log.info("dms_skipped", extra=p))

    # Allow orchestrator to pause on alert
    async def _pause_on_alert(_p: dict[str, Any]) -> None:
        try:
            await orch.pause()
        except Exception:
            _log.exception("orch_pause_failed")

    orch.on(EVT.ALERTS_ALERTMANAGER, _pause_on_alert)

    # Wire protective exits (need bus pushed inside)
    exits.attach_bus(bus)
    orch.on(EVT.HEALTH_REPORT, exits.on_health_report)

    return orch


# ----------------------------- Telegram Commands -----------------------------
def _make_telegram_cmds(*, bus: UnifiedEventBus, settings: Any, storage: StorageFacade) -> TelegramBotCommands:
    return TelegramBotCommands(bus=bus, settings=settings, storage=storage)


# ----------------------------- Public compose() -----------------------------
def compose(settings: Any) -> AppWiring:
    _log.info("compose.start")

    # Bus/Storage/Broker
    bus = _make_bus(settings)
    storage = _make_storage(settings)

    # Broker may require retry on cold start (network)
    broker = make_broker(
        exchange=getattr(settings, "EXCHANGE", "gateio"),
        api_key=getattr(settings, "API_KEY", ""),
        secret=getattr(settings, "API_SECRET", ""),
        password=getattr(settings, "API_PASSWORD", None),
        sandbox=bool(getattr(settings, "SANDBOX", False)),
        rate_limit_ms=int(getattr(settings, "RATE_LIMIT_MS", 1000) or 1000),
    )

    # Risk / Exits / Health / Safety
    risk = _make_risk(settings)
    exits = _make_protective_exits(bus=bus, settings=settings)
    health = _make_health(storage=storage, broker=broker, settings=settings)
    safety = _make_safety(bus=bus, broker=broker, settings=settings)

    # Use-cases
    eval_and_execute, execute_trade = _make_use_cases(
        settings=settings, storage=storage, broker=broker, bus=bus, risk=risk
    )

    # Orchestrator
    orchestrator = _make_orchestrator(
        settings=settings,
        bus=bus,
        eval_and_execute=eval_and_execute,
        execute_trade=execute_trade,
        storage=storage,
        risk=risk,
        exits=exits,
    )

    # Subscribers (Telegram alerts)
    attach_alerts(bus, settings)

    # Some helpful helpers
    async def _daily_pnl_quote(symbol: str) -> Decimal:
        try:
            repo = getattr(storage, "reports", None)
            if not repo:
                return dec("0")
            if hasattr(repo, "daily_pnl_quote"):
                v = repo.daily_pnl_quote(symbol)
                return dec(str(v))
            return dec("0")
        except Exception:
            _log.debug("_daily_pnl_quote_failed", exc_info=True)
            return dec("0")

    async def _balances_series(storage: Any, symbol: str, limit: int = 48) -> list[Decimal]:
        try:
            repo = getattr(storage, "reports", None)
            if not repo or not hasattr(repo, "balances_series"):
                return []
            arr = repo.balances_series(symbol=symbol, limit=limit)
            return [dec(str(x)) for x in arr]
        except Exception:
            _log.debug("_balances_series_failed", exc_info=True)
            return []

    _log.info("compose.done")

    return AppWiring(
        settings=settings,
        storage=storage,
        broker=broker,
        bus=bus,
        risk=risk,
        exits=exits,
        orchestrator=orchestrator,
        eval_and_execute=eval_and_execute,
        execute_trade=execute_trade,
        health=health,
        telegram_cmd=_make_telegram_cmds(bus=bus, settings=settings, storage=storage),
        safety=safety,
    )
