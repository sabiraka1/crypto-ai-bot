from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.core.domain.strategies.position_sizing import (
    SizeConstraints,
    fixed_fractional,
    fixed_quote_amount,
    kelly_sized_quote,
    volatility_target_size,
)
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.eval_and_execute")


@dataclass(frozen=True)
class MarketData:
    """Контейнер рыночных данных для стратегий."""
    last_price: Decimal
    bid: Decimal
    ask: Decimal
    spread_pct: Decimal
    volatility_pct: Decimal
    samples: int
    timeframe: str


@dataclass(frozen=True)
class StrategyContext:
    """Контекст для выполнения стратегии."""
    mode: str
    now_ms: int | None = None


async def _build_market_data(*, symbol: str, broker: Any, settings: Any) -> MarketData:
    timeframe = str(getattr(settings, "STRAT_TIMEFRAME", "1m") or "1m")
    limit = int(getattr(settings, "STRAT_OHLCV_LIMIT", 200) or 200)
    closes = []
    try:
        exch = getattr(broker, "exchange", None)
        if exch and hasattr(exch, "fetch_ohlcv"):
            ohlcv = await exch.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            closes = [dec(str(x[4])) for x in (ohlcv or [])]
    except Exception:
        _log.error("md_fetch_ohlcv_failed", extra={"symbol": symbol, "timeframe": timeframe}, exc_info=True)

    bid = ask = last = dec("0")
    try:
        t = await broker.fetch_ticker(symbol)
        bid = dec(str(getattr(t, "bid", t.get("bid", "0")) or "0"))
        ask = dec(str(getattr(t, "ask", t.get("ask", "0")) or "0"))
        last = dec(str(getattr(t, "last", t.get("last", "0")) or "0"))
    except Exception:
        _log.error("md_fetch_ticker_failed", extra={"symbol": symbol}, exc_info=True)

    spread_pct = dec("0")
    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_pct = (ask - bid) / mid * dec("100")

    vol_pct = dec("0")
    if len(closes) >= 5:
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
        if rets:
            mean = sum(rets) / dec(str(len(rets)))
            var = sum((r - mean) * (r - mean) for r in rets) / dec(str(len(rets)))
            std = dec(str(math.sqrt(float(var))))
            vol_pct = std * dec("100")

    return MarketData(
        last_price=last,
        bid=bid,
        ask=ask,
        spread_pct=spread_pct,
        volatility_pct=vol_pct,
        samples=len(closes),
        timeframe=timeframe,
    )


class StrategyManager:
    """Простая обертка для вызова стратегий."""
    def __init__(self, settings: Any, regime_provider: Any = None) -> None:
        self.settings = settings
        self.regime_provider = regime_provider

    async def decide(self, ctx: StrategyContext, md: MarketData) -> tuple[str, str | None]:
        """Упрощенная логика для принятия решения."""
        # Здесь должна быть реальная логика стратегий
        # Для примера возвращаем hold
        return "hold", "no_strategy_configured"


async def eval_and_execute(
    *,
    symbol: str,
    storage: Any,
    broker: Any,
    bus: Any,
    risk: Any,
    exits: Any,
    settings: Any,
) -> dict[str, Any]:
    try:
        md = await _build_market_data(symbol=symbol, broker=broker, settings=settings)

        # Получаем regime из GatedBroker если он есть
        regime = "neutral"  # default
        if hasattr(broker, "_regime") and broker._regime:
            try:
                regime = await broker._regime.regime()
            except Exception:
                _log.warning("regime_detector_failed", exc_info=True)

        ctx = StrategyContext(mode=str(getattr(settings, "MODE", "paper") or "paper"), now_ms=None)
        manager = StrategyManager(settings=settings, regime_provider=lambda: regime)
        decision, explain = await manager.decide(ctx=ctx, md=md)

        if decision not in ("buy", "sell"):
            inc("strategy_hold_total", symbol=symbol, reason=explain or "")
            return {"ok": True, "action": "hold", "reason": explain, "regime": regime}

        # ----------------- Position sizing -----------------
        quote_balance: Decimal = dec("0")
        try:
            bal = await broker.fetch_balance()
            quote_ccy = symbol.split("/")[1]
            info = bal.get(quote_ccy, {}) if isinstance(bal, dict) else {}
            free = info.get("free") or info.get("total")
            if free is not None:
                quote_balance = dec(str(free))
        except Exception:
            _log.error("sizing_balance_failed", extra={"symbol": symbol}, exc_info=True)

        constraints = SizeConstraints(
            max_quote_pct=dec(str(getattr(settings, "SIZE_MAX_QUOTE_PCT", "0"))) if getattr(settings, "SIZE_MAX_QUOTE_PCT", None) else None,
            min_quote=dec(str(getattr(settings, "SIZE_MIN_QUOTE", "0"))) if getattr(settings, "SIZE_MIN_QUOTE", None) else None,
            max_quote=dec(str(getattr(settings, "SIZE_MAX_QUOTE", "0"))) if getattr(settings, "SIZE_MAX_QUOTE", None) else None,
        )

        quote_amount = base_amount = dec("0")
        sizer = str(getattr(settings, "POSITION_SIZER", "fractional") or "fractional").lower()

        if decision == "buy":
            if sizer == "fixed":
                quote_amount = fixed_quote_amount(
                    fixed=dec(str(getattr(settings, "FIXED_AMOUNT", "0") or "0")),
                    constraints=constraints,
                    free_quote_balance=quote_balance,
                )
            elif sizer == "volatility":
                quote_amount = volatility_target_size(
                    free_quote_balance=quote_balance,
                    market_vol_pct=md.volatility_pct,
                    target_portfolio_vol_pct=dec(str(getattr(settings, "TARGET_PORTFOLIO_VOL_PCT", "0.5") or "0.5")),
                    base_fraction=dec(str(getattr(settings, "STRAT_QUOTE_FRACTION", "0.05") or "0.05")),
                    constraints=constraints,
                )
            elif sizer == "kelly":
                quote_amount = kelly_sized_quote(
                    free_quote_balance=quote_balance,
                    win_rate=dec(str(getattr(settings, "KELLY_WIN_RATE", "0.5") or "0.5")),
                    avg_win_pct=dec(str(getattr(settings, "KELLY_AVG_WIN_PCT", "1.0") or "1.0")),
                    avg_loss_pct=dec(str(getattr(settings, "KELLY_AVG_LOSS_PCT", "1.0") or "1.0")),
                    base_fraction=dec(str(getattr(settings, "STRAT_QUOTE_FRACTION", "0.05") or "0.05")),
                    constraints=constraints,
                )
            else:  # fractional (дефолт)
                quote_amount = fixed_fractional(
                    free_quote_balance=quote_balance,
                    fraction=dec(str(getattr(settings, "STRAT_QUOTE_FRACTION", "0.05") or "0.05")),
                    constraints=constraints,
                )

        # ----------------- Risk check -----------------
        try:
            ok_risk, risk_reason = (risk.check(symbol=symbol, storage=storage)
                                    if hasattr(risk, "check")
                                    else (risk.can_execute(), "legacy_risk"))
        except Exception:
            ok_risk, risk_reason = False, "risk_exception"
        
        if not ok_risk:
            inc("risk_block_total", symbol=symbol, reason=str(risk_reason))
            return {"ok": True, "action": "hold", "reason": f"risk:{risk_reason}", "regime": regime}

        # ----------------- Execute trade -----------------
        res = await execute_trade(
            symbol=symbol,
            side=decision,
            storage=storage,
            broker=broker,
            bus=bus,
            settings=settings,
            exchange=getattr(settings, "EXCHANGE", ""),
            quote_amount=quote_amount,
            base_amount=base_amount,
            risk_manager=risk,
            protective_exits=exits,
        )
        return {"ok": True, "action": decision, "result": res, "explain": explain, "regime": regime, "sizer": sizer}
    except Exception as exc:
        _log.error("eval_and_execute_failed", extra={"symbol": symbol}, exc_info=True)
        return {"ok": False, "error": str(exc)}