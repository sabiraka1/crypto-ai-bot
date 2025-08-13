# src/crypto_ai_bot/trading/signals/score_fusion.py
"""
🔀 Score Fusion — умная комбинация сигналов
Сохраняет API FusionResult, поддерживает стратегии через params (config/context),
детектирует конфликт и возвращает confidence для риск-модуляции.
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class FusionStrategy(Enum):
    WEIGHTED = "weighted"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    ADAPTIVE = "adaptive"
    CONSENSUS = "consensus"
    CONFIDENCE = "confidence"


@dataclass
class FusionResult:
    final_score: float
    strategy_used: str
    rule_score: float
    ai_score: float
    confidence: float
    conflict_detected: bool
    fusion_details: Dict[str, Any]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def detect_conflict(rule_score: float, ai_score: float, threshold: float = 0.3) -> bool:
    return abs(float(rule_score) - float(ai_score)) > float(threshold)


def calculate_confidence(rule_score: float, ai_score: float,
                         data_quality: Optional[Dict] = None) -> float:
    try:
        base = (rule_score + ai_score) / 2.0
        conflict_penalty = abs(rule_score - ai_score) * 0.5
        extreme_penalty = 0.1 * sum([rule_score > 0.95, rule_score < 0.05,
                                     ai_score > 0.95, ai_score < 0.05])
        data_penalty = 0.0
        if data_quality:
            failed = len(data_quality.get("timeframes_failed", []))
            ind_cnt = int(data_quality.get("indicators_count", 0))
            if failed > 0: data_penalty += 0.05 * failed
            if ind_cnt < 5: data_penalty += 0.10
        return clamp(base - conflict_penalty - extreme_penalty - data_penalty)
    except Exception:
        return 0.5


def fuse_weighted(rule_score: float, ai_score: float, alpha: float = 0.6) -> float:
    return clamp(alpha * rule_score + (1 - alpha) * ai_score)


def fuse_conservative(rule_score: float, ai_score: float) -> float:
    return min(rule_score, ai_score)


def fuse_aggressive(rule_score: float, ai_score: float) -> float:
    return max(rule_score, ai_score)


def fuse_consensus(rule_score: float, ai_score: float, threshold: float = 0.6) -> float:
    return (rule_score + ai_score) / 2.0 if (rule_score >= threshold and ai_score >= threshold) else min(rule_score, ai_score)


def fuse_confidence(rule_score: float, ai_score: float,
                    rule_confidence: float = 0.8, ai_confidence: float = 0.6) -> float:
    tot = rule_confidence + ai_confidence
    if tot == 0: return (rule_score + ai_score) / 2.0
    return clamp((rule_score * rule_confidence + ai_score * ai_confidence) / tot)


def fuse_adaptive(rule_score: float, ai_score: float, context: Optional[Dict] = None) -> Tuple[float, Dict]:
    details: Dict[str, Any] = {"sub_strategy": "adaptive"}
    try:
        is_conflict = detect_conflict(rule_score, ai_score, threshold=0.3)
        both_high = rule_score >= 0.7 and ai_score >= 0.7
        both_low = rule_score <= 0.3 and ai_score <= 0.3

        if both_high and not is_conflict:
            result = (rule_score + ai_score) / 2.0 + 0.05
            details["sub_strategy"] = "both_high_bonus"
        elif both_low:
            result = fuse_conservative(rule_score, ai_score)
            details["sub_strategy"] = "both_low_conservative"
        elif is_conflict:
            if context and context.get("market_volatility", "normal") == "high":
                result = fuse_weighted(rule_score, ai_score, alpha=0.8)
                details["sub_strategy"] = "conflict_rules_priority"
            else:
                result = fuse_consensus(rule_score, ai_score, threshold=0.5)
                details["sub_strategy"] = "conflict_consensus"
        elif rule_score > ai_score + 0.2:
            result = fuse_weighted(rule_score, ai_score, alpha=0.8)
            details["sub_strategy"] = "rules_dominant"
        elif ai_score > rule_score + 0.2:
            result = fuse_weighted(rule_score, ai_score, alpha=0.4)
            details["sub_strategy"] = "ai_dominant"
        else:
            result = fuse_weighted(rule_score, ai_score, alpha=0.6)
            details["sub_strategy"] = "balanced"

        details.update({
            "is_conflict": is_conflict,
            "both_high": both_high,
            "both_low": both_low,
            "score_diff": abs(rule_score - ai_score),
        })
        return clamp(result), details
    except Exception as e:
        logger.error(f"❌ Adaptive fusion failed: {e}")
        return fuse_weighted(rule_score, ai_score), {"sub_strategy": "fallback", "error": str(e)}


def fuse_scores(rule_score: float, ai_score: float,
                strategy: str = "adaptive",
                config: Optional[Dict] = None,
                context: Optional[Dict] = None) -> FusionResult:
    logger.debug(f"🔀 Fusing scores: rule={rule_score:.3f}, ai={ai_score:.3f}, strategy={strategy}")
    try:
        rule_score = clamp(rule_score); ai_score = clamp(ai_score)
        conflict_threshold = (config or {}).get("conflict_threshold", 0.3)
        is_conflict = detect_conflict(rule_score, ai_score, conflict_threshold)

        fusion_details: Dict[str, Any] = {
            "input_rule_score": rule_score,
            "input_ai_score": ai_score,
            "conflict_threshold": conflict_threshold,
        }

        if strategy == FusionStrategy.WEIGHTED.value:
            alpha = (config or {}).get("alpha", 0.6)
            final = fuse_weighted(rule_score, ai_score, alpha)
            fusion_details["alpha"] = alpha
        elif strategy == FusionStrategy.CONSERVATIVE.value:
            final = fuse_conservative(rule_score, ai_score)
        elif strategy == FusionStrategy.AGGRESSIVE.value:
            final = fuse_aggressive(rule_score, ai_score)
        elif strategy == FusionStrategy.CONSENSUS.value:
            thr = (config or {}).get("consensus_threshold", 0.6)
            final = fuse_consensus(rule_score, ai_score, thr)
            fusion_details["consensus_threshold"] = thr
        elif strategy == FusionStrategy.CONFIDENCE.value:
            rconf = (config or {}).get("rule_confidence", 0.8)
            aconf = (config or {}).get("ai_confidence", 0.6)
            final = fuse_confidence(rule_score, ai_score, rconf, aconf)
            fusion_details.update({"rule_confidence": rconf, "ai_confidence": aconf})
        elif strategy == FusionStrategy.ADAPTIVE.value:
            final, det = fuse_adaptive(rule_score, ai_score, context)
            fusion_details.update(det)
        else:
            logger.warning(f"⚠️ Unknown strategy '{strategy}', fallback to weighted")
            final = fuse_weighted(rule_score, ai_score)
            fusion_details["fallback"] = True

        confidence = calculate_confidence(rule_score, ai_score, (context or {}).get("data_quality"))
        res = FusionResult(
            final_score=final,
            strategy_used=strategy,
            rule_score=rule_score,
            ai_score=ai_score,
            confidence=confidence,
            conflict_detected=is_conflict,
            fusion_details=fusion_details,
        )
        if is_conflict:
            logger.warning(f"⚠️ Score conflict: rule={rule_score:.3f}, ai={ai_score:.3f}")
        logger.info(f"🔀 Fusion result: {final:.3f} (strategy={strategy}, conf={confidence:.3f})")
        return res
    except Exception as e:
        logger.error(f"❌ Score fusion failed: {e}", exc_info=True)
        fb = (float(rule_score) + float(ai_score)) / 2.0
        return FusionResult(final_score=clamp(fb), strategy_used="emergency_fallback",
                            rule_score=float(rule_score), ai_score=float(ai_score),
                            confidence=0.3, conflict_detected=True, fusion_details={"error": str(e)})


__all__ = [
    "fuse_scores", "FusionResult", "FusionStrategy",
    "clamp", "detect_conflict"
]
