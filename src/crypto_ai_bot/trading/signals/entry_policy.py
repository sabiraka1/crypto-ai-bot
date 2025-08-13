# src/crypto_ai_bot/trading/signals/entry_policy.py
"""
🎯 Entry Policy — умная система входа
- Динамический SL через RiskManager (если доступен df_15m), иначе fallback на ATR-мультипликаторы
- TP от ATR (или от R:R при отсутствии ATR)
- Адаптивный порог входа и умное позиционирование (confidence/volatility-aware)
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


# ── модели/DTO ───────────────────────────────────────────────────────────────
@dataclass
class EntryDecision:
    enter: bool
    reason: str
    symbol: str
    side: str
    size_usd: float
    confidence: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    threshold_used: Optional[float] = None
    sizing_details: Optional[Dict[str, Any]] = None
    decision_factors: Optional[Dict[str, Any]] = None


# ── helpers ──────────────────────────────────────────────────────────────────
def _atr_pct(ind: Dict[str, Any]) -> Optional[float]:
    atr, price = ind.get("atr"), ind.get("price")
    if atr and price and price > 0:
        return (atr / price) * 100
    return None


def _extract_df_15m(feats: Dict[str, Any]):
    """
    Пытаемся достать DataFrame 15m из разных возможных мест в фичах.
    Поддерживает варианты: feats['df_15m'], feats['frames']['15m'], feats['dataframe'], feats['ohlcv_15m'].
    """
    # прямой ключ
    df = feats.get("df_15m")
    if df is not None:
        return df
    # словарь фреймов
    frames = feats.get("frames") or feats.get("dataframes") or {}
    for key in ("15m", "m15", "tf_15m"):
        if key in frames:
            return frames[key]
    # единичный датафрейм, иногда агрегатор кладёт его как "dataframe"
    df = feats.get("dataframe") or feats.get("ohlcv_15m")
    return df


def _infer_market_condition(feats: Dict[str, Any], ind: Dict[str, Any]) -> str:
    """
    Простой маппер состояния рынка для RiskManager:
    - feats['context_summary']['market_condition'] приоритетно, иначе из индикаторов
    """
    cs = feats.get("context_summary") or {}
    mc = cs.get("market_condition")
    if isinstance(mc, str) and mc:
        return mc

    # Если известно направление 4h
    if ind.get("trend_4h_bull") is True:
        return "STRONG_BULL"
    if ind.get("trend_4h_bull") is False:
        return "WEAK_BEAR"

    # Локальный EMA-режим 15m на всякий случай
    ema20, ema50 = ind.get("ema20"), ind.get("ema50")
    if isinstance(ema20, (int, float)) and isinstance(ema50, (int, float)):
        if ema20 > ema50:
            return "WEAK_BULL"
        if ema20 < ema50:
            return "WEAK_BEAR"

    return "SIDEWAYS"


# ── адаптивные пороги/сайзинг ────────────────────────────────────────────────
def calculate_adaptive_threshold(cfg: Settings, feats: Dict[str, Any]) -> float:
    base = float(getattr(cfg, "MIN_SCORE_TO_BUY", 0.65))
    ind = feats.get("indicators", {})
    dq = feats.get("data_quality", {})
    thr = base

    # волатильность — через ATR_PCT_MIN/MAX
    atrp = _atr_pct(ind)
    if atrp is not None:
        atr_min = float(getattr(cfg, "ATR_PCT_MIN", 0.3))
        atr_max = float(getattr(cfg, "ATR_PCT_MAX", 10.0))
        if atrp > atr_max:
            thr *= 1.15       # на очень высокой волатильности — выше порог
        elif atrp < atr_min:
            thr *= 0.95       # на сонном рынке — чуть ниже

    # качество данных
    failed = len(dq.get("timeframes_failed", []))
    if failed > 0:
        thr *= 1.0 + 0.05 * failed
    if dq.get("indicators_count", 0) < 5:
        thr *= 1.10

    # RSI перегрет/перепродан
    rsi = ind.get("rsi")
    if isinstance(rsi, (int, float)):
        if rsi > 80:
            thr *= 1.10
        elif rsi < 20:
            thr *= 0.90

    # «тонкие» часы (UTC)
    hour = datetime.now(timezone.utc).hour
    if hour < 6 or hour > 22:
        thr *= 1.05

    # конфликт фьюжна — небольшой надбавкой к порогу
    if feats.get("conflict_detected") or feats.get("fusion", {}).get("conflict_detected"):
        thr += 0.05

    return max(0.0, min(1.0, thr))


def calculate_intelligent_position_size(cfg: Settings, state: StateManager,
                                        feats: Dict[str, Any], score: float) -> Tuple[float, Dict[str, Any]]:
    base_usd = float(getattr(cfg, "POSITION_SIZE_USD", getattr(cfg, "TRADE_AMOUNT", 100)))
    risk_per_trade = float(getattr(cfg, "RISK_PER_TRADE", 0.02))
    equity = float(getattr(state, "equity", 1000.0))
    max_risk_usd = equity * risk_per_trade

    # уверенность: из fusion/context или используем score
    conf = feats.get("confidence") or feats.get("fusion", {}).get("confidence") or score
    conf_factor = 1.0
    if conf >= 0.8:
        conf_factor = 1.2
    elif conf <= 0.4:
        conf_factor = 0.7

    # вола → размер
    ind = feats.get("indicators", {})
    atrp = _atr_pct(ind)
    vol_factor = 1.0
    if atrp is not None:
        atr_max = float(getattr(cfg, "ATR_PCT_MAX", 10.0))
        atr_min = float(getattr(cfg, "ATR_PCT_MIN", 0.3))
        if atrp > atr_max:
            vol_factor = 0.75
        elif atrp < atr_min:
            vol_factor = 1.10

    # конфликт → аккуратнее
    if feats.get("conflict_detected") or feats.get("fusion", {}).get("conflict_detected"):
        conf_factor *= 0.8

    adjusted = base_usd * conf_factor * vol_factor
    final_size = min(adjusted, max_risk_usd)

    min_size = float(getattr(cfg, "MIN_POSITION_SIZE", 10.0))
    final_size = max(final_size, min_size) if final_size > 0 else 0.0

    return final_size, {
        "base_usd": base_usd,
        "equity": equity,
        "max_risk_usd": max_risk_usd,
        "confidence": conf,
        "conf_factor": conf_factor,
        "vol_factor": vol_factor,
        "final_size": final_size,
        "risk_per_trade_pct": risk_per_trade * 100,
    }


# ── расчёт SL/TP ─────────────────────────────────────────────────────────────
def _tp_from_atr_or_rr(cfg: Settings, ind: Dict[str, Any], entry_price: float, stop_loss: float) -> Optional[float]:
    """
    Возвращает TP:
      - если ATR есть: entry + ATR * TP_MULT
      - иначе: entry + (entry - SL) * RR (RR по умолчанию 2.0)
    """
    atr = ind.get("atr")
    if atr and atr > 0:
        tp_k = float(getattr(cfg, "TP_ATR_MULTIPLIER", 3.0))
        return entry_price + atr * tp_k

    # без ATR — ставим целевой RR
    rr_target = 2.0
    if stop_loss and entry_price and stop_loss < entry_price:
        return entry_price + (entry_price - stop_loss) * rr_target
    return None


# ── итоговое решение ─────────────────────────────────────────────────────────
def analyze_decision_factors(cfg: Settings, state: StateManager,
                             feats: Dict[str, Any], score: float) -> Dict[str, Any]:
    ind = feats.get("indicators", {})
    atrp = _atr_pct(ind)
    hour = datetime.now(timezone.utc).hour
    start_h = int(getattr(cfg, "TRADING_HOUR_START", 0))
    end_h = int(getattr(cfg, "TRADING_HOUR_END", 24))
    return {
        "score": score,
        "rsi": ind.get("rsi"),
        "atr": ind.get("atr"),
        "atr_pct": atrp,
        "trading_hours": start_h <= hour < end_h,
        "data_quality": feats.get("data_quality", {}),
    }


def decide_entry(cfg: Settings, state: StateManager, risk: RiskManager,
                 feats: Dict[str, Any], score: float) -> Dict[str, Any]:
    logger.info(f"🎯 Entry decision: score={score:.3f}")

    try:
        # 1) факторы и порог
        factors = analyze_decision_factors(cfg, state, feats, score)
        thr = calculate_adaptive_threshold(cfg, feats)
        if score < thr:
            reason = f"score_below_adaptive_threshold:{score:.3f}<{thr:.3f}"
            logger.info(f"❎ Entry denied: {reason}")
            return {"enter": False, "reason": reason, "score": score,
                    "threshold_used": thr, "decision_factors": factors}

        # 2) базовые индикаторы
        ind = feats.get("indicators", {})
        price = ind.get("price")
        if not price:
            return {"enter": False, "reason": "no_price"}

        # базовый гейт по ATR%
        atrp = _atr_pct(ind)
        atr_max = float(getattr(cfg, "ATR_PCT_MAX", 10.0))
        if atrp is not None and atrp > atr_max:
            return {"enter": False, "reason": f"excessive_volatility:{atrp:.2f}%>{atr_max:.2f}%"}

        # 3) размер позиции
        size, sizing = calculate_intelligent_position_size(cfg, state, feats, score)
        if size <= 0:
            return {"enter": False, "reason": "zero_position_size", "sizing_details": sizing}

        # 4) SL — предпочтительно динамический от RiskManager
        market_condition = _infer_market_condition(feats, ind)
        df_15m = _extract_df_15m(feats)
        sl = None
        sl_details = {}

        if df_15m is not None:
            try:
                sl, sl_details = risk.calculate_dynamic_stop_loss(
                    entry_price=float(price),
                    df=df_15m,
                    market_condition=market_condition
                )
            except Exception as e:
                logger.warning(f"Dynamic SL failed, fallback to ATR-based: {e}")

        if sl is None:
            # fallback: ATR-мультипликатор
            atr = ind.get("atr")
            if not atr or atr <= 0:
                return {"enter": False, "reason": "no_atr_for_sl"}
            sl_k = float(getattr(cfg, "SL_ATR_MULTIPLIER", 2.0))
            sl = float(price) - float(atr) * sl_k

            # жёсткие кэпы для безопасности
            sl = max(sl, float(price) * 0.95)  # не шире 5% вниз
            sl_details = {"mode": "fallback_atr", "sl_k": sl_k, "atr": atr}

        # 5) TP
        tp = _tp_from_atr_or_rr(cfg, ind, float(price), float(sl))
        if tp is None or not (sl < price < tp):
            return {"enter": False, "reason": "invalid_sl_tp"}

        # 6) метрики риска и финальное решение
        risk_pct = ((float(price) - float(sl)) / float(price)) * 100
        rr = (float(tp) - float(price)) / (float(price) - float(sl)) if (float(price) - float(sl)) > 0 else None

        decision = EntryDecision(
            enter=True, reason="entry_approved",
            symbol=getattr(cfg, "SYMBOL", "BTC/USDT"), side="buy",
            size_usd=float(size), confidence=float(feats.get("confidence", score)),
            entry_price=float(price), stop_loss=float(sl), take_profit=float(tp),
            risk_pct=risk_pct, risk_reward_ratio=rr, threshold_used=thr,
            sizing_details={**sizing, "sl_details": sl_details},
            decision_factors=factors
        )
        logger.info(
            f"✅ Entry APPROVED: {decision.symbol} ${decision.size_usd:.0f} "
            f"(score={score:.3f}>{thr:.3f}, R:R={(rr if rr is not None else 'N/A')})"
        )

        return {
            "enter": True,
            "symbol": decision.symbol,
            "side": decision.side,
            "size_usd": decision.size_usd,
            "score": score,
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "confidence": decision.confidence,
            "risk_pct": decision.risk_pct,
            "risk_reward_ratio": decision.risk_reward_ratio,
            "threshold_used": decision.threshold_used,
            "sizing_details": decision.sizing_details,
            "decision_factors": decision.decision_factors,
            "reason": decision.reason,
        }

    except Exception as e:
        logger.error(f"❌ Entry decision failed: {e}", exc_info=True)
        return {"enter": False, "reason": f"decision_error:{str(e)}", "score": score}


__all__ = [
    "decide_entry", "EntryDecision",
    "calculate_adaptive_threshold", "calculate_intelligent_position_size"
]
