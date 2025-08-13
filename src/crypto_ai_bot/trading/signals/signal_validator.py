"""
🛡️ Signal Validator - Гибридная версия
Объединяет практичность и компактность твоего кода с диагностикой моего
"""

import logging
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any, Optional
import pandas as pd

from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager

logger = logging.getLogger(__name__)


def _tf_minutes(tf: str) -> int:
    """🕐 Конвертация таймфрейма в минуты (твоя умная функция)"""
    s = (tf or "15m").strip().lower()
    try:
        if s.endswith("m"): return int(s[:-1])
        if s.endswith("h"): return int(s[:-1]) * 60
        if s.endswith("d"): return int(s[:-1]) * 1440
    except Exception:
        pass
    return 15


def validate_features(cfg: Settings, state: StateManager, feats: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    🛡️ Главная функция валидации с логированием (твоя быстрая основа)
    """
    logger.debug("🛡️ Starting signal validation")
    reasons: List[str] = []

    try:
        # Используем твои компактные проверки
        reasons += _validate_data_quality(cfg, feats)
        reasons += _validate_risk_limits(cfg, state)
        reasons += _validate_market_conditions(cfg, feats)
        reasons += _validate_time_windows(cfg)
        reasons += _validate_technical_conditions(cfg, feats)

        ok = len(reasons) == 0
        
        # Улучшенное логирование
        if not ok:
            logger.warning(f"❌ Signal validation failed: {reasons}")
        else:
            logger.info("✅ Signal validation passed")
            
        return ok, reasons
        
    except Exception as e:
        logger.error(f"❌ Signal validation error: {e}", exc_info=True)
        return False, ["validation_error"]


def _validate_data_quality(cfg: Settings, feats: Dict[str, Any]) -> List[str]:
    """📊 Проверка качества данных (твоя логика + мои улучшения)"""
    reasons: List[str] = []
    
    try:
        # Твоя быстрая проверка ошибок
        if "error" in feats:
            reasons.append(f"data_error:{feats['error']}")
            logger.warning(f"⚠️ Data error detected: {feats['error']}")
            return reasons

        # Твоя проверка обязательных полей
        req_fields = ["symbol", "rule_score", "ai_score", "indicators"]
        missing = [f for f in req_fields if f not in feats]
        if missing:
            reasons.append(f"missing_fields:{','.join(missing)}")
            logger.warning(f"⚠️ Missing required fields: {missing}")

        dq = feats.get("data_quality", {})
        failed = dq.get("timeframes_failed", [])

        # Твоя проверка основного таймфрейма
        primary_tf = feats.get("timeframe", "15m")
        if primary_tf in failed:
            reasons.append(f"primary_timeframe_failed:{primary_tf}")
            logger.warning(f"⚠️ Primary timeframe {primary_tf} data failed")

        # Твоя умная динамическая проверка stale данных
        ts = feats.get("timestamp")
        if ts:
            try:
                ts_dt = pd.to_datetime(ts)
                minutes = (pd.Timestamp.now(tz="UTC") - ts_dt).total_seconds() / 60.0
                max_age = 2 * _tf_minutes(primary_tf)  # Твоя формула!
                
                if minutes > max_age:
                    reasons.append(f"stale_data:{minutes:.1f}min>{max_age}min")
                    logger.warning(f"⚠️ Stale data: {minutes:.1f} min > {max_age} min")
            except Exception:
                reasons.append("invalid_timestamp")

        # Твои проверки количества
        primary_candles = dq.get("primary_candles", 0)
        if primary_candles < 50:
            reasons.append(f"insufficient_candles:{primary_candles}<50")
            logger.warning(f"⚠️ Insufficient candles: {primary_candles} < 50")
            
        if dq.get("indicators_count", 0) == 0:
            reasons.append("no_indicators")
            logger.warning("⚠️ No technical indicators available")

        logger.debug(f"📊 Data quality check: {len(reasons)} issues found")
        return reasons
        
    except Exception as e:
        logger.error(f"❌ Data quality validation failed: {e}")
        return ["data_quality_check_failed"]


def _validate_risk_limits(cfg: Settings, state: StateManager) -> List[str]:
    """🚨 Проверка риск-лимитов (твоя логика + мои fallbacks)"""
    reasons: List[str] = []
    
    try:
        # Твоя умная проверка позиций с fallbacks
        max_pos = int(getattr(cfg, "MAX_CONCURRENT_POS", 2))
        cur = 0
        
        if hasattr(state, "get_open_positions_count"):
            cur = state.get_open_positions_count()
        elif hasattr(state, "open_positions"):
            cur = getattr(state, "open_positions", 0)
        else:
            # Твой fallback
            state_data = getattr(state, "state", {})
            cur = 1 if state_data.get("in_position", False) else 0
            
        if cur >= max_pos:
            reasons.append(f"too_many_positions:{cur}>={max_pos}")
            logger.warning(f"🚨 Too many positions: {cur}/{max_pos}")

        # Твоя проверка просадки
        max_dd = float(getattr(cfg, "DAILY_MAX_DRAWDOWN", 0.06))
        dd = 0.0
        
        if hasattr(state, "get_daily_drawdown"):
            dd = float(state.get_daily_drawdown())
        elif hasattr(state, "daily_drawdown"):
            dd = float(getattr(state, "daily_drawdown", 0.0))
        else:
            # Мой fallback
            state_data = getattr(state, "state", {})
            dd = abs(float(state_data.get("daily_pnl_pct", 0.0)))
            
        if dd >= max_dd:
            reasons.append(f"daily_kill_switch:{dd:.3f}>={max_dd:.3f}")
            logger.error(f"🚨 Daily kill switch triggered: {dd:.1%} >= {max_dd:.1%}")

        logger.debug(f"🚨 Risk limits check: positions={cur}/{max_pos}, drawdown={dd:.3f}/{max_dd:.3f}")
        return reasons
        
    except Exception as e:
        logger.error(f"❌ Risk limits validation failed: {e}")
        return ["risk_limits_check_failed"]


def _validate_market_conditions(cfg: Settings, feats: Dict[str, Any]) -> List[str]:
    """📈 Проверка рыночных условий (твоя синхронизация + мои проверки)"""
    reasons: List[str] = []
    
    try:
        ind = feats.get("indicators", {})

        # Твоя умная синхронизация настроек волатильности
        price = ind.get("price", 0.0)
        atr = ind.get("atr", None)
        atr_pct = (atr / price) * 100 if atr and price else None

        # Твоя логика объединения настроек
        atr_min = float(getattr(cfg, "ATR_PCT_MIN",
                       getattr(cfg, "MIN_VOLATILITY_PCT", 0.3)))
        atr_max = float(getattr(cfg, "ATR_PCT_MAX",
                       getattr(cfg, "MAX_VOLATILITY_PCT", 10.0)))

        if atr_pct is not None:
            if atr_pct < atr_min:
                reasons.append(f"low_volatility:{atr_pct:.2f}%<{atr_min:.2f}%")
                logger.warning(f"📈 Low volatility: {atr_pct:.2f}% < {atr_min:.2f}%")
            if atr_pct > atr_max:
                reasons.append(f"high_volatility:{atr_pct:.2f}%>{atr_max:.2f}%")
                logger.warning(f"📈 High volatility: {atr_pct:.2f}% > {atr_max:.2f}%")

        # Твоя проверка ликвидности
        vol = ind.get("volume")
        vol_sma = ind.get("volume_sma")
        if vol and vol_sma and vol_sma > 0:
            ratio = vol / vol_sma
            min_ratio = float(getattr(cfg, "MIN_VOLUME_RATIO", 0.3))
            if ratio < min_ratio:
                reasons.append(f"low_liquidity:{ratio:.2f}<{min_ratio:.2f}")
                logger.warning(f"📈 Low liquidity: volume ratio {ratio:.2f}")

        # Твоя проверка экстремального RSI
        rsi = ind.get("rsi", None)
        if rsi is not None:
            if rsi > 90:
                reasons.append(f"extreme_overbought:rsi={rsi:.1f}")
                logger.warning(f"📈 Extreme overbought: RSI {rsi:.1f}")
            elif rsi < 10:
                reasons.append(f"extreme_oversold:rsi={rsi:.1f}")
                logger.warning(f"📈 Extreme oversold: RSI {rsi:.1f}")

        logger.debug(f"📈 Market conditions check: {len(reasons)} issues found")
        return reasons
        
    except Exception as e:
        logger.error(f"❌ Market conditions validation failed: {e}")
        return ["market_conditions_check_failed"]


def _validate_time_windows(cfg: Settings) -> List[str]:
    """🕐 Проверка временных ограничений (твоя основа + мое улучшенное логирование)"""
    reasons: List[str] = []
    
    try:
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()
        
        # Твоя проверка торговых часов
        start_h = int(getattr(cfg, "TRADING_HOUR_START", 0))
        end_h = int(getattr(cfg, "TRADING_HOUR_END", 24))
        
        if not (start_h <= hour < end_h):
            reasons.append(f"outside_trading_hours:{hour}h")
            logger.info(f"🕐 Outside trading hours: {hour}h not in [{start_h}h, {end_h}h)")

        # Твоя проверка выходных (для крипты чаще выключено)
        if bool(getattr(cfg, "DISABLE_WEEKEND_TRADING", False)) and weekday >= 5:
            weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            reasons.append(f"weekend_trading_disabled:{weekday_names[weekday]}")
            logger.info(f"🕐 Weekend trading disabled: {weekday_names[weekday]}")

        logger.debug(f"🕐 Time windows check: {hour}h, {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][weekday]}")
        return reasons
        
    except Exception as e:
        logger.error(f"❌ Time windows validation failed: {e}")
        return ["time_windows_check_failed"]


def _validate_technical_conditions(cfg: Settings, feats: Dict[str, Any]) -> List[str]:
    """⚙️ Проверка технических условий (твоя торговая логика + мои проверки)"""
    reasons: List[str] = []
    
    try:
        rule_score = float(feats.get("rule_score", 0.0))
        ai_score = float(feats.get("ai_score", 0.0))

        # Твои проверки минимальных порогов
        min_rule = float(getattr(cfg, "MIN_RULE_SCORE", 0.0))
        min_ai = float(getattr(cfg, "MIN_AI_SCORE", 0.0))
        
        if rule_score < min_rule:
            reasons.append(f"low_rule_score:{rule_score:.3f}<{min_rule:.3f}")
            logger.debug(f"⚙️ Low rule score: {rule_score:.3f} < {min_rule:.3f}")
            
        if ai_score < min_ai:
            reasons.append(f"low_ai_score:{ai_score:.3f}<{min_ai:.3f}")
            logger.debug(f"⚙️ Low AI score: {ai_score:.3f} < {min_ai:.3f}")

        # Твоя проверка расхождения scores
        diff = abs(rule_score - ai_score)
        max_div = float(getattr(cfg, "MAX_SCORE_DIVERGENCE", 0.5))
        if diff > max_div:
            reasons.append(f"score_divergence:{diff:.3f}>{max_div:.3f}")
            logger.warning(f"⚙️ High score divergence: rule={rule_score:.3f}, ai={ai_score:.3f}")

        # Твоя расширенная проверка индикаторов
        ind = feats.get("indicators", {})
        required = getattr(cfg, "REQUIRED_INDICATORS",
                          ["price","rsi","atr","ema20","ema50"])
        missing = [k for k in required if k not in ind]
        if missing:
            reasons.append(f"missing_indicators:{','.join(missing)}")
            logger.warning(f"⚙️ Missing required indicators: {missing}")

        # Твоя умная проверка мультифрейм тренда (лонг-только)
        if "ema20_4h" in ind and "ema50_4h" in ind:
            if ind["ema20_4h"] < ind["ema50_4h"]:
                reasons.append("higher_tf_bear_trend_4h")
                logger.info("⚙️ 4H bear trend detected, blocking long entry")

        logger.debug(f"⚙️ Technical conditions check: {len(reasons)} issues found")
        return reasons
        
    except Exception as e:
        logger.error(f"❌ Technical conditions validation failed: {e}")
        return ["technical_conditions_check_failed"]


def get_validation_stats(cfg: Settings, state: StateManager, feats: Dict[str, Any]) -> Dict[str, Any]:
    """
    📊 Детальная статистика валидации (моя диагностическая функция)
    
    Returns:
        Dict с подробной информацией о всех проверках
    """
    try:
        stats = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                "data_quality": _validate_data_quality(cfg, feats),
                "risk_limits": _validate_risk_limits(cfg, state),
                "market_conditions": _validate_market_conditions(cfg, feats),
                "time_windows": _validate_time_windows(cfg),
                "technical_conditions": _validate_technical_conditions(cfg, feats),
            }
        }
        
        # Суммарная статистика
        all_reasons = []
        for check_reasons in stats["checks"].values():
            all_reasons.extend(check_reasons)
        
        stats["summary"] = {
            "valid": len(all_reasons) == 0,
            "total_issues": len(all_reasons),
            "all_reasons": all_reasons,
            "checks_performed": list(stats["checks"].keys()),
        }
        
        # Контекстная информация
        indicators = feats.get("indicators", {})
        stats["context"] = {
            "symbol": feats.get("symbol"),
            "timeframe": feats.get("timeframe"),
            "score": {"rule": feats.get("rule_score"), "ai": feats.get("ai_score")},
            "price": indicators.get("price"),
            "atr_pct": (indicators.get("atr", 0) / indicators.get("price", 1)) * 100 if indicators.get("price") else None,
            "rsi": indicators.get("rsi"),
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Validation stats failed: {e}")
        return {"error": str(e)}


# ── Экспорт ──────────────────────────────────────────────────────────────────
__all__ = ["validate_features", "get_validation_stats"]