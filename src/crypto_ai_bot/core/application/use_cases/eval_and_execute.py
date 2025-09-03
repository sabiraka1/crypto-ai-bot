from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

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

# === AI skeleton imports (безопасные, есть фолбэк) ===
try:
    from crypto_ai_bot.core.domain.signals.feature_pipeline import Candle, last_features
    from crypto_ai_bot.core.domain.signals.ai_scoring import AIScorer, AIScoringConfig
    from crypto_ai_bot.core.domain.signals.fusion import pass_thresholds, FusionThresholds
except Exception:  # если папки ещё не добавили — всё равно не ломаемся
    Candle = None  # type: ignore
    last_features = None  # type: ignore
    AIScorer = None  # type: ignore
    AIScoringConfig = None  # type: ignore
    pass_thresholds = None  # type: ignore
    FusionThresholds = None  # type: ignore

_log = get_logger("usecase.eval_and_execute")


@dataclass(frozen=True)
class MarketData:
    last_price: Decimal
    bid: Decimal
    ask: Decimal
    spread_pct: Decimal
    volatility_pct: Decimal
    samples: int
    timeframe: str


@dataclass(frozen=True)
class StrategyContext:
    mode: str
    now_ms: int | None = None


async def _fetch_ohlcv_as_candles(broker: Any, symbol: str, timeframe: str, limit: int) -> list[Candle]:
    """Унифицированная загрузка OHLCV и преобразование в Candle (если модуль доступен).
    При ошибке возвращает пустой список — логика не ломается.
    """
    out: list[Candle] = []
    if Candle is None:
        return out
    try:
        exch = getattr(broker, "exchange", None)
        if exch and hasattr(exch, "fetch_ohlcv"):
            ohlcv = await exch.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            for row in (ohlcv or []):
                # CCXT формирует: [ts, open, high, low, close, volume]
                out.append(Candle(t=int(row[0]), o=dec(str(row[1])), h=dec(str(row[2])),
                                  l=dec(str(row[3])), c=dec(str(row[4])), v=dec(str(row[5]))))
    except Exception:
        _log.error("ohlcv_fetch_failed", extra={"symbol": symbol, "timeframe": timeframe}, exc_info=True)
    return out


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


def _heuristic_ind_score_from_features(feats: dict[str, float]) -> float:
    """Простой и безопасный индикаторный скор без сторонних зависимостей.
    Скейл 0..100. Используется только если включён AI-gating.
    """
    score = 50.0
    ema20 = feats.get("ema20_15m", 0.0)
    ema50 = feats.get("ema50_15m", 0.0)
    macd = feats.get("macd_15m", 0.0)
    macds = feats.get("macds_15m", 0.0)
    rsi = feats.get("rsi14_15m", 50.0)
    bb_u = feats.get("bb_u_15m", 0.0)
    bb_m = feats.get("bb_m_15m", 0.0)
    bb_l = feats.get("bb_l_15m", 0.0)

    # Тренд: EMA20 > EMA50
    if ema20 > ema50:
        score += 10
    else:
        score -= 5

    # MACD > Signal
    if macd > macds:
        score += 10
    else:
        score -= 5

    # RSI зона
    if 55 <= rsi <= 70:
        score += 10
    elif rsi > 70:
        score += 5
    elif rsi < 45:
        score -= 10

    # Положение относительно средины Боллинджера
    if bb_u and bb_m and bb_l:
        if bb_m > 0:
            # близко к верхней половине канала — лёгкий плюс
            score += 5 if (ema20 > bb_m) else 0

    # Нормировка
    return max(0.0, min(100.0, score))


class StrategyManager:
    def __init__(self, settings: Any, regime_provider: Any = None) -> None:
        self.settings = settings
        self.regime_provider = regime_provider

    async def decide(self, ctx: StrategyContext, md: MarketData) -> tuple[str, str | None]:
        # здесь может быть логика стратегий; по умолчанию — hold
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

        # regime (не ломаем поведение)
        regime = "neutral"
        if hasattr(broker, "_regime") and broker._regime:
            try:
                regime = await broker._regime.regime()
            except Exception:
                _log.warning("regime_detector_failed", exc_info=True)

        ctx = StrategyContext(mode=str(getattr(settings, "MODE", "paper") or "paper"), now_ms=None)
        manager = StrategyManager(settings=settings, regime_provider=lambda: regime)
        decision, explain = await manager.decide(ctx=ctx, md=md)

        # === AI-gating (строго опционально) ===
        ai_gating = bool(int(getattr(settings, "AI_GATING_ENABLED", 0) or 0))
        if ai_gating and decision in ("buy", "sell") and AIScorer and last_features and Candle:
            # Подготовим OHLCV для мульти-TF
            limit = int(getattr(settings, "STRAT_OHLCV_LIMIT", 200) or 200)
            # Базовый TF: 15m (если у тебя другой — подставится как есть)
            tf_15m = str(getattr(settings, "STRAT_TIMEFRAME", "15m") or "15m")
            o15 = await _fetch_ohlcv_as_candles(broker, symbol, tf_15m, limit)
            o1h = await _fetch_ohlcv_as_candles(broker, symbol, "1h", 200)
            o4h = await _fetch_ohlcv_as_candles(broker, symbol, "4h", 200)
            o1d = await _fetch_ohlcv_as_candles(broker, symbol, "1d", 200)
            o1w = await _fetch_ohlcv_as_candles(broker, symbol, "1w", 200)

            feats = last_features(o15, o1h, o4h, o1d, o1w)
            ind_score = _heuristic_ind_score_from_features(feats)

            # Настройка AI: можно переопределить путями в settings при желании
            cfg = AIScoringConfig(
                model_path=str(getattr(settings, "AI_MODEL_PATH", "models/ai/model.onnx") or "models/ai/model.onnx"),
                meta_path=str(getattr(settings, "AI_META_PATH", "models/ai/meta.json") or "models/ai/meta.json"),
                required=bool(int(getattr(settings, "AI_REQUIRED", 0) or 0)),
            )
            scorer = AIScorer(cfg)
            ai_score: Optional[float] = None
            try:
                ai_score = scorer.score(o15, o1h, o4h, o1d, o1w)
            except Exception:
                _log.error("ai_score_failed", extra={"symbol": symbol}, exc_info=True)

            ok, dbg = pass_thresholds(
                ind_score=ind_score,
                ai_score=ai_score,
                regime=("bull" if regime == "bull" else "bear" if regime == "bear" else "neutral"),
            )

            if not ok:
                inc("strategy_hold_total", symbol=symbol, reason=f"ai_gating:{dbg.get('reason','')}")
                return {"ok": True, "action": "hold", "reason": f"ai_gating:{dbg}", "regime": regime}

        if decision not in ("buy", "sell"):
            inc("strategy_hold_total", symbol=symbol, reason=explain or "")
            return {"ok": True, "action": "hold", "reason": explain, "regime": regime}

        # ----------------- Position sizing (совместимо с CCXT и paper) -----------------
        quote_balance: Decimal = dec("0")
        quote_ccy = symbol.split("/")[1]
        bal = None
        try:
            # 1) попробуем CCXT-стиль (по символу): {"free_base","free_quote"}
            try:
                bal = await broker.fetch_balance(symbol)  # ccxt_adapter поддерживает symbol
            except TypeError:
                bal = await broker.fetch_balance()        # paper-стиль без аргумента

            if isinstance(bal, dict):
                if "free_quote" in bal:  # CCXT-адаптер
                    qb = bal.get("free_quote")
                    if qb is not None:
                        quote_balance = dec(str(qb))
                elif quote_ccy in bal:  # словарь по активам (paper)
                    info = bal.get(quote_ccy, {}) or {}
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
            else:  # fractional
                quote_amount = fixed_fractional(
                    free_quote_balance=quote_balance,
                    fraction=dec(str(getattr(settings, "STRAT_QUOTE_FRACTION", "0.05") or "0.05")),
                    constraints=constraints,
                )

        # ----------------- Risk check (как было) -----------------
        try:
            ok_risk, risk_reason = (risk.check(symbol=symbol, storage=storage)
                                    if hasattr(risk, "check")
                                    else (risk.can_execute(), "legacy_risk"))
        except Exception:
            ok_risk, risk_reason = False, "risk_exception"

        if not ok_risk:
            inc("risk_block_total", symbol=symbol, reason=str(risk_reason))
            return {"ok": True, "action": "hold", "reason": f"risk:{risk_reason}", "regime": regime}

        # ----------------- Execute trade (как было) -----------------
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
