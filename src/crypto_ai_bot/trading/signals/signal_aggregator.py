# src/crypto_ai_bot/trading/signals/signal_aggregator.py
"""
🎯 Signal Aggregator — сбор и агрегация торговых сигналов
Фичи: true ATR (Wilder) с опцией UNIFIED ATR, EMA9/21/20/50, MACD(12,26,9),
Bollinger(20,2), breakout_high_20, volume_ratio, мультифрейм (15m/1h/4h),
контекстные штрафы/бонусы по BTC.D/DXY/Fear&Greed/market_condition.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.context.snapshot import ContextSnapshot

logger = logging.getLogger(__name__)

# ── Импорты с безопасным fallback ────────────────────────────────────────────
try:
    from crypto_ai_bot.analysis.technical_indicators import (
        calculate_all_indicators as _calc_inds,
        get_unified_atr as _unified_atr,
    )
except Exception as e:
    _calc_inds = None
    _unified_atr = None
    logger.warning(f"signal_aggregator: indicators fallback ({e})")

try:
    # Если есть твой «умный» скоулер — используем его
    from crypto_ai_bot.trading.signals.score_fusion import fuse_scores as _fuse_scores
except Exception:
    _fuse_scores = None


# ── Утилиты ──────────────────────────────────────────────────────────────────
def _to_df(ohlcv) -> pd.DataFrame:
    if not ohlcv:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna()
    except Exception as e:
        logger.error(f"❌ DataFrame conversion failed: {e}")
        return pd.DataFrame()


def _fetch_multiframe_data(ex: ExchangeClient, symbol: str,
                           timeframes: List[str], limit: int = 200) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    failed: List[str] = []
    for tf in timeframes:
        try:
            ohlcv = ex.get_ohlcv(symbol, timeframe=tf, limit=limit)
            df = _to_df(ohlcv)
            out[tf] = df
            if df.empty:
                failed.append(tf)
                logger.warning(f"⚠️ No {tf} data for {symbol}")
            else:
                logger.debug(f"✅ {tf}: {len(df)} candles {df.index[0]}→{df.index[-1]}")
        except Exception as e:
            out[tf] = pd.DataFrame()
            failed.append(tf)
            logger.error(f"❌ Fetch {tf} failed: {e}")
    if failed:
        logger.warning(f"⚠️ Failed timeframes: {failed}")
    return out


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _wilder_atr(df: pd.DataFrame, period: int = 14) -> float:
    """True ATR (Wilder): TR = max(H-L, |H-Cprev|, |L-Cprev|); ATR = EMA(alpha=1/period)."""
    if df is None or df.empty:
        return float("nan")
    h, l, c = df["high"], df["low"], df["close"]
    c_prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    val = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float("nan")
    return val


def _bbands(close: pd.Series, period: int = 20, mult: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    up = mid + mult * std
    dn = mid - mult * std
    return mid, up, dn


# ── Индикаторы (fallback, если нет analysis.calculate_all_indicators) ────────
def _compute_basic_indicators(df15: pd.DataFrame,
                              df1h: Optional[pd.DataFrame] = None,
                              df4h: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    if df15 is None or df15.empty or len(df15) < 50:
        return {}

    close = df15["close"]; high = df15["high"]; low = df15["low"]; vol = df15["volume"]

    # EMA / SMA
    ema9 = _ema(close, 9).iloc[-1]
    ema21 = _ema(close, 21).iloc[-1]
    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    sma20 = close.rolling(20).mean().iloc[-1]

    # MACD(12,26,9)
    ema12 = _ema(close, 12); ema26 = _ema(close, 26)
    macd_line = (ema12 - ema26)
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = (macd_line - macd_signal).iloc[-1]

    # RSI(14) простой
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = float(100 - (100 / (1 + rs))) if pd.notna(rs.iloc[-1]) else 50.0

    # ATR: предпочитаем UNIFIED ATR из analysis, иначе Wilder
    atr = None
    try:
        if _unified_atr:
            atr = float(_unified_atr(df15, period=14, method="ewm"))
    except Exception:
        atr = None
    if atr is None or np.isnan(atr):
        atr = _wilder_atr(df15, 14)

    price = float(close.iloc[-1])
    atr_pct = (atr / price) * 100 if price > 0 and pd.notna(atr) else float("nan")

    # Bollinger(20,2) + re-entry
    bb_mid, bb_up, bb_dn = _bbands(close, 20, 2.0)
    bb_mid_v = float(bb_mid.iloc[-1]) if pd.notna(bb_mid.iloc[-1]) else None
    bb_up_v = float(bb_up.iloc[-1]) if pd.notna(bb_up.iloc[-1]) else None
    bb_dn_v = float(bb_dn.iloc[-1]) if pd.notna(bb_dn.iloc[-1]) else None
    bb_reentry = False
    if len(close) > 1 and pd.notna(bb_dn.iloc[-2]) and pd.notna(bb_dn.iloc[-1]):
        bb_reentry = (close.iloc[-2] < bb_dn.iloc[-2]) and (close.iloc[-1] > bb_dn.iloc[-1])

    # Breakout high 20
    if len(high) >= 21:
        prev_high20 = high.shift(1).rolling(20).max().iloc[-1]
        breakout_high_20 = price > prev_high20 if pd.notna(prev_high20) else False
    else:
        breakout_high_20 = False

    # Volume + ratio
    volume = float(vol.iloc[-1])
    volume_sma = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else float("nan")
    volume_ratio = (volume / volume_sma) if volume_sma and volume_sma > 0 else float("nan")

    # Мультифрейм-тренды (EMA20/EMA50) на 1h/4h
    ema20_1h = ema50_1h = ema20_4h = ema50_4h = None
    trend_1h_bull = trend_4h_bull = None
    if df1h is not None and not df1h.empty:
        ema20_1h = float(_ema(df1h["close"], 20).iloc[-1])
        ema50_1h = float(_ema(df1h["close"], 50).iloc[-1])
        if all(pd.notna([ema20_1h, ema50_1h])):
            trend_1h_bull = ema20_1h > ema50_1h
    if df4h is not None and not df4h.empty:
        ema20_4h = float(_ema(df4h["close"], 20).iloc[-1])
        ema50_4h = float(_ema(df4h["close"], 50).iloc[-1])
        if all(pd.notna([ema20_4h, ema50_4h])):
            trend_4h_bull = ema20_4h > ema50_4h

    indicators: Dict[str, Any] = {
        "price": price,
        "ema9": float(ema9), "ema21": float(ema21),
        "ema20": float(ema20), "ema50": float(ema50),
        "sma_20": float(sma20) if pd.notna(sma20) else None,
        "macd_hist": float(macd_hist) if pd.notna(macd_hist) else None,
        "rsi": float(rsi) if pd.notna(rsi) else 50.0,
        "atr": float(atr) if pd.notna(atr) else None,
        "atr_pct": float(atr_pct) if pd.notna(atr_pct) else None,
        "bb_mid": bb_mid_v, "bb_up": bb_up_v, "bb_dn": bb_dn_v,
        "bb_reentry": bool(bb_reentry),
        "breakout_high_20": bool(breakout_high_20),
        "volume": float(volume) if pd.notna(volume) else None,
        "volume_sma": float(volume_sma) if pd.notna(volume_sma) else None,
        "volume_ratio": float(volume_ratio) if pd.notna(volume_ratio) else None,
        "ema20_1h": ema20_1h, "ema50_1h": ema50_1h,
        "ema20_4h": ema20_4h, "ema50_4h": ema50_4h,
        "trend_1h_bull": trend_1h_bull,
        "trend_4h_bull": trend_4h_bull,
    }
    # Чистим None/NaN
    return {k: v for k, v in indicators.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}


def _compute_indicators_safe(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    try:
        df15 = frames.get("15m") or next((frames[t] for t in ("15m",) if t in frames), pd.DataFrame())
        df1h = frames.get("1h", pd.DataFrame())
        df4h = frames.get("4h", pd.DataFrame())
        if df15.empty:
            logger.warning("⚠️ No 15m data for indicators computation")
            return {}
        if callable(_calc_inds):
            try:
                return _calc_inds(df15, df1h if not df1h.empty else None, df4h if not df4h.empty else None) or {}
            except Exception as e:
                logger.warning(f"⚠️ calculate_all_indicators failed: {e}, using fallback")
        return _compute_basic_indicators(df15, df1h if not df1h.empty else None, df4h if not df4h.empty else None)
    except Exception as e:
        logger.error(f"❌ Indicators computation failed: {e}")
        return {}


# ── Rule-score ───────────────────────────────────────────────────────────────
def _simple_rule_score(ind: Dict[str, Any]) -> float:
    """Простой rule-score (RSI/MACD/EMA/объём/BB/мультифрейм)."""
    if not ind:
        return 0.5
    score = 0.0

    rsi = ind.get("rsi", 50)
    if rsi < 30:
        score += 0.20
    elif 35 <= rsi <= 65:
        score += 0.15

    if ind.get("macd_hist", 0) > 0:
        score += 0.20

    if ind.get("ema9", 0) > ind.get("ema21", 0):
        score += 0.15
    if ind.get("ema20", 0) > ind.get("ema50", 0):
        score += 0.15

    vr = ind.get("volume_ratio", float("nan"))
    if isinstance(vr, (int, float)) and not np.isnan(vr):
        score += min(0.20, 0.10 * vr)

    if ind.get("bb_reentry"):
        score += 0.10

    # мультифрейм-бонус/штраф
    if ind.get("trend_4h_bull") is True:
        score += 0.10
    if ind.get("trend_4h_bull") is False:
        score -= 0.10

    return max(0.0, min(1.0, score))


def _compute_rule_score_safe(indicators: Dict[str, Any], ctx: ContextSnapshot) -> float:
    try:
        if callable(_fuse_scores) and indicators:
            return float(max(0.0, min(1.0, _fuse_scores(indicators))))
        return _simple_rule_score(indicators)
    except Exception as e:
        logger.warning(f"⚠️ Rule score failed: {e}")
        return 0.6


# ── Контекст ────────────────────────────────────────────────────────────────
def _ctx_summary(ctx: ContextSnapshot) -> Dict[str, Any]:
    """
    Безопасная сводка контекста под наши имена полей.
    Поддерживает как новые (btc_dominance_delta_24h) так и старые (btc_d_delta_24h).
    """
    def _get(obj, name: str, default=None):
        try:
            v = getattr(obj, name)
            return v if v is not None else default
        except Exception:
            return default

    # возможные имена:
    btc_dom = (
        _get(ctx, "btc_dominance_delta_24h") or
        _get(ctx, "btc_d_delta_24h") or
        0.0
    )
    dxy = (
        _get(ctx, "dxy_delta_5d") or
        _get(ctx, "dxy_delta") or
        0.0
    )
    fng = _get(ctx, "fear_greed", None)
    mc = (_get(ctx, "market_condition", "SIDEWAYS") or "SIDEWAYS").upper()

    return {
        "btc_d_rising": bool(btc_dom > 0.5),   # рост доминации — отриц. для альтов
        "dxy_rising_fast": bool(dxy > 1.0),    # сильный доллар
        "fear_greed": fng,
        "market_condition": mc,
    }


# ── Главная функция ─────────────────────────────────────────────────────────
def aggregate_features(cfg: Settings, ex: ExchangeClient, ctx: Optional[ContextSnapshot]) -> Dict[str, Any]:
    """
    Возвращает компактный словарь с индикаторами, скором и summary контекста.
    cfg, ex — берём из DI; ctx допускает None (подменяется нейтральным).
    """
    symbol = getattr(cfg, "SYMBOL", "BTC/USDT")
    primary_tf = getattr(cfg, "TIMEFRAME", "15m")
    tfs = getattr(cfg, "ANALYSIS_TIMEFRAMES", [primary_tf, "1h", "4h"])
    limit = int(getattr(cfg, "OHLCV_LIMIT", 200))

    logger.info(f"🎯 Aggregating features for {symbol} ({tfs}, limit={limit})")
    ctx = ctx or ContextSnapshot.neutral()

    try:
        frames = _fetch_multiframe_data(ex, symbol, tfs, limit)
        primary_df = frames.get(primary_tf, pd.DataFrame())
        if primary_df.empty:
            return {
                "error": "no_primary_data",
                "symbol": symbol,
                "timeframe": primary_tf,
                "timestamp": pd.Timestamp.now(tz="UTC").isoformat()
            }

        indicators = _compute_indicators_safe(frames)

        # дозаполним объём/ratio если их нет (нормально для fallback)
        if "volume" not in indicators and not primary_df.empty:
            indicators["volume"] = float(primary_df["volume"].iloc[-1])
        if "volume_sma" not in indicators and not primary_df.empty and len(primary_df) >= 20:
            indicators["volume_sma"] = float(primary_df["volume"].rolling(20).mean().iloc[-1])
        if "volume_ratio" not in indicators and indicators.get("volume_sma", 0) > 0:
            indicators["volume_ratio"] = indicators["volume"] / indicators["volume_sma"]

        rule_score = _compute_rule_score_safe(indicators, ctx)

        # AI score — пока берём failover из конфигурации (если ИИ выключен)
        ai_score = float(getattr(cfg, "AI_FAILOVER_SCORE", 0.5))

        ctx_sum = _ctx_summary(ctx)

        result: Dict[str, Any] = {
            "symbol": symbol,
            "timeframe": primary_tf,
            "timestamp": primary_df.index[-1].isoformat(),
            "rule_score": float(round(rule_score, 4)),
            "ai_score": float(round(ai_score, 4)),
            "indicators": indicators,
            "context": {
                "btc_dominance_delta_24h": getattr(ctx, "btc_dominance_delta_24h", None),
                "dxy_delta_5d": getattr(ctx, "dxy_delta_5d", None),
                "fear_greed": getattr(ctx, "fear_greed", None),
                "market_condition": getattr(ctx, "market_condition", "SIDEWAYS"),
            },
            "context_summary": ctx_sum,
            "data_quality": {
                "timeframes_ok": [tf for tf, df in frames.items() if not df.empty],
                "timeframes_failed": [tf for tf, df in frames.items() if df.empty],
                "indicators_count": len(indicators),
                "primary_candles": len(primary_df),
            },
        }

        logger.info(
            f"✅ Features aggregated: rule={result['rule_score']:.3f}, "
            f"ai={result['ai_score']:.3f}, ind={len(indicators)}"
        )
        return result

    except Exception as e:
        logger.error(f"❌ Feature aggregation failed: {e}", exc_info=True)
        return {
            "error": "aggregation_failed",
            "error_details": str(e),
            "symbol": symbol,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat()
        }


__all__ = ["aggregate_features"]
