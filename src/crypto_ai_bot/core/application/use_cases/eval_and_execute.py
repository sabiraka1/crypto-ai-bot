from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.macro.regime_detector import RegimeConfig, RegimeDetector
from crypto_ai_bot.core.application.use_cases.execute_trade import execute_trade
from crypto_ai_bot.core.domain.strategies import MarketData, StrategyContext, StrategyManager
from crypto_ai_bot.core.domain.strategies.position_sizing import (
    SizeConstraints,
    fixed_fractional,
    fixed_quote_amount,
    kelly_sized_quote,
    volatility_target_size,
)
from crypto_ai_bot.core.infrastructure.macro.sources.http_btc_dominance import BtcDominanceSource
from crypto_ai_bot.core.infrastructure.macro.sources.http_dxy import DxySource
from crypto_ai_bot.core.infrastructure.macro.sources.http_fomc import FomcSource
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("usecase.eval_and_execute")


async def _http_get_json_factory(settings: Any):
    try:
        from crypto_ai_bot.utils.http_client import HttpClient
        client = HttpClient(timeout=float(getattr(settings, "HTTP_TIMEOUT", 5.0) or 5.0))
        async def _get(url: str):
            return await client.get_json(url)
        return _get
    except Exception:
        async def _missing(_url: str):
            raise RuntimeError("no_http_client")
        return _missing


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


async def eval_and_execute(
    *,
    symbol: str,
    storage: Any,
    broker: Any,
    bus: Any,
    risk: Any,
    exits: Any,
    settings: Any,
) -> dict:
    try:
        md = await _build_market_data(symbol=symbol, broker=broker, settings=settings)

        # Regime detector (мягко)
        http_get_json = await _http_get_json_factory(settings)
        dxy = DxySource(http_get_json=http_get_json, url=getattr(settings, "DXY_SOURCE_URL", None))
        btd = BtcDominanceSource(http_get_json=http_get_json, url=getattr(settings, "BTC_DOM_SOURCE_URL", None))
        fomc = FomcSource(http_get_json=http_get_json, url=getattr(settings, "FOMC_CALENDAR_URL", None))
        cfg = RegimeConfig(
            dxy_up_pct=float(getattr(settings, "REGIME_DXY_UP_PCT", 0.5) or 0.5),
            dxy_down_pct=float(getattr(settings, "REGIME_DXY_DOWN_PCT", -0.2) or -0.2),
            btc_dom_up_pct=float(getattr(settings, "REGIME_BTC_DOM_UP_PCT", 0.5) or 0.5),
            btc_dom_down_pct=float(getattr(settings, "REGIME_BTC_DOM_DOWN_PCT", -0.5) or -0.5),
            fomc_block_minutes=int(getattr(settings, "REGIME_FOMC_BLOCK_MIN", 60) or 60),
        )
        detector = RegimeDetector(dxy_source=dxy, btc_dom_source=btd, fomc_source=fomc, cfg=cfg)
        regime = await detector.regime()

        ctx = StrategyContext(mode=str(getattr(settings, "MODE", "paper") or "paper"), now_ms=None)
        manager = StrategyManager(settings=settings, regime_provider=lambda r=regime: r)
        decision, explain = await manager.decide(ctx=ctx, md=md)

        if decision not in ("buy", "sell"):
            inc("strategy_hold_total", symbol=symbol, reason=explain or "")
            return {"ok": True, "action": "hold", "reason": explain, "regime": regime}

        # ----------------- Position sizing -----------------
        # читаем свободный баланс в котируемой
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
