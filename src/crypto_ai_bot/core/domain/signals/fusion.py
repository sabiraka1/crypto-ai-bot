"""
Fusion module for combining technical and AI signals.

According to README:
- Technical signal: 65% weight
- AI model signal: 35% weight
- Adaptive thresholds based on market regime
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple, Dict, Any

from crypto_ai_bot.core.domain.macro.types import RegimeState
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# -------------------- types --------------------

class SignalDirection(Enum):
    """Trading signal direction (SPOT: LONG/NEUTRAL)."""
    LONG = "long"
    SHORT = "short"      # зарезервировано (для фьючерсов), в SPOT не используется
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class FusionConfig:
    """
    Configuration for signal fusion.

    Default weights from README: 65% technical, 35% AI
    Thresholds are on a 0-100 scale.
    """
    # Base weights
    technical_weight: float = 0.65
    ai_weight: float = 0.35

    # Confidence thresholds by regime
    # (чем «хуже» режим → тем выше порог входа)
    risk_on_threshold: float = 55.0     # bull
    risk_small_threshold: float = 60.0  # light risk-on
    neutral_threshold: float = 65.0     # no-entry режим; используется как справочный
    risk_off_threshold: float = 70.0    # bear

    # AI abstain (зона неопределённости, где ИИ «молчит»)
    ai_abstain_low: float = 45.0
    ai_abstain_high: float = 55.0

    # Minimal per-source requirements
    min_technical_score: float = 40.0
    min_ai_score: float = 30.0

    # Adaptive tuning
    enable_adaptive: bool = True
    volatility_factor: float = 0.2  # 0..1, влияние волатильности на порог

    def __post_init__(self) -> None:
        # weights must sum ~1.0
        total = self.technical_weight + self.ai_weight
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")
        # thresholds sanity
        for v in (
            self.risk_on_threshold, self.risk_small_threshold,
            self.neutral_threshold, self.risk_off_threshold,
            self.ai_abstain_low, self.ai_abstain_high,
            self.min_technical_score, self.min_ai_score,
        ):
            if not (0.0 <= v <= 100.0):
                raise ValueError("All thresholds must be within [0, 100]")
        # abstain zone sanity
        if self.ai_abstain_low >= self.ai_abstain_high:
            raise ValueError("AI abstain zone must satisfy low < high")
        # volatility factor
        if not (0.0 <= self.volatility_factor <= 1.0):
            raise ValueError("volatility_factor must be in [0, 1]")


@dataclass(frozen=True)
class FusionSignal:
    """
    Result of signal fusion.

    combined_score — то, что сравнивается с порогом (0..100).
    confidence — 0..1 (чем выше над порогом, тем увереннее).
    """
    direction: SignalDirection
    combined_score: float          # 0-100
    technical_score: float         # 0-100
    ai_score: Optional[float]      # 0-100 or None
    confidence: float              # 0-1
    passed: bool
    reason: str
    metadata: Dict[str, Any]
    timestamp: datetime

    def should_trade(self) -> bool:
        """True если сигнал проходит порог и не NEUTRAL."""
        return self.passed and self.direction != SignalDirection.NEUTRAL


# -------------------- fusion --------------------

class SignalFusion:
    """
    Combine technical and AI signals into unified decision,
    with adaptive thresholds based on market regime & volatility.
    """

    def __init__(self, config: Optional[FusionConfig] = None) -> None:
        self.config = config or FusionConfig()
        _log.info(
            "signal_fusion_initialized",
            extra={
                "technical_weight": self.config.technical_weight,
                "ai_weight": self.config.ai_weight,
                "adaptive": self.config.enable_adaptive,
            },
        )

    # -------- public API --------

    def fuse_signals(
        self,
        technical_score: float,
        ai_score: Optional[float],
        regime: RegimeState,
        direction: SignalDirection = SignalDirection.LONG,
        volatility: Optional[float] = None,
    ) -> FusionSignal:
        """
        Combine technical and AI scores into a single decision.

        Args:
            technical_score: 0..100
            ai_score: 0..100 (или None, если ИИ недоступен)
            regime: текущий рыночный режим
            direction: желаемое направление (для SPOT фактически LONG/NEUTRAL)
            volatility: относительный индикатор волатильности (например, ratio к среднему)

        Returns:
            FusionSignal
        """
        t = _clamp_0_100(technical_score)
        a = _clamp_0_100(ai_score) if ai_score is not None else None

        # Базовый порог по режиму + адаптация
        thr_base = self._get_regime_threshold(regime)
        thr_effective = self._adapt_threshold(thr_base, volatility)

        abstain_applied = False

        # Если ИИ в «абстейн»-зоне — поднимаем требования и игнорируем AI
        if a is not None and self.config.ai_abstain_low <= a <= self.config.ai_abstain_high:
            _log.info(
                "ai_in_abstain_zone",
                extra={"ai_score": a, "zone": (self.config.ai_abstain_low, self.config.ai_abstain_high)},
            )
            thr_effective = min(100.0, thr_effective + 10.0)
            a = None
            abstain_applied = True

        # Если AI отсутствует — чуть повышаем порог
        if a is None:
            combined = t
            thr_for_check = min(100.0, thr_effective + 5.0)
            conf = self._confidence_technical_only(t, thr_for_check)
        else:
            combined = t * self.config.technical_weight + a * self.config.ai_weight
            thr_for_check = thr_effective
            conf = self._confidence_fusion(t, a, combined, thr_for_check)

        passed, reason = self._check_signal(t, a, combined, thr_for_check, regime)

        final_dir = direction if passed else SignalDirection.NEUTRAL

        meta = {
            "regime": regime.value,
            "threshold_base": thr_base,
            "threshold_effective": thr_effective,
            "threshold_used": thr_for_check,
            "technical_weight": self.config.technical_weight,
            "ai_weight": self.config.ai_weight if a is not None else 0.0,
            "volatility": volatility,
            "ai_abstain_applied": abstain_applied,
        }

        return FusionSignal(
            direction=final_dir,
            combined_score=float(combined),
            technical_score=float(t),
            ai_score=float(a) if a is not None else None,
            confidence=float(conf),
            passed=passed,
            reason=reason,
            metadata=meta,
            timestamp=datetime.now(timezone.utc),
        )

    # -------- internals --------

    def _get_regime_threshold(self, regime: RegimeState) -> float:
        """Базовый порог по режиму."""
        return {
            RegimeState.RISK_ON: self.config.risk_on_threshold,
            RegimeState.RISK_SMALL: self.config.risk_small_threshold,
            RegimeState.NEUTRAL: self.config.neutral_threshold,  # в NEUTRAL новых входов нет
            RegimeState.RISK_OFF: self.config.risk_off_threshold,
        }[regime]

    def _adapt_threshold(self, threshold: float, volatility: Optional[float]) -> float:
        """
        Адаптация порога по волатильности:
        - высокая волатильность → слегка снизить порог (больше возможностей),
        - низкая волатильность → слегка повысить порог.
        Ограничения: не ниже 50 и не выше 80.
        """
        if not self.config.enable_adaptive or volatility is None:
            return threshold

        vf = self.config.volatility_factor
        thr = threshold

        try:
            v = float(volatility)
        except Exception:
            return threshold

        if v > 1.0:  # high vol
            adj = min(5.0, (v - 1.0) * vf * 10.0)
            thr = max(50.0, thr - adj)
        elif v < 0.5:  # low vol
            adj = min(5.0, (0.5 - v) * vf * 10.0)
            thr = min(80.0, thr + adj)

        return float(thr)

    def _check_signal(
        self,
        technical_score: float,
        ai_score: Optional[float],
        combined_score: float,
        threshold: float,
        regime: RegimeState,
    ) -> Tuple[bool, str]:
        """
        Проверяет минимальные требования и пороги по режимам.
        Возвращает (passed, reason).
        """
        # per-source minima
        if technical_score < self.config.min_technical_score:
            return False, f"technical_below_minimum({technical_score:.1f}<{self.config.min_technical_score:.1f})"
        if ai_score is not None and ai_score < self.config.min_ai_score:
            return False, f"ai_below_minimum({ai_score:.1f}<{self.config.min_ai_score:.1f})"

        # regime logic (README):
        # - RISK_OFF: можно входить только при «исключительных» условиях (комбинированный >= threshold)
        # - NEUTRAL: NO ENTRY
        # - RISK_ON / RISK_SMALL: обычная проверка порога
        if regime == RegimeState.NEUTRAL:
            return False, "neutral_regime_no_entry"

        if combined_score < threshold:
            tag = "risk_off_threshold_not_met" if regime == RegimeState.RISK_OFF else "threshold_not_met"
            return False, f"{tag}({combined_score:.1f}<{threshold:.1f})"

        # All checks passed
        return (True, f"{'fusion' if ai_score is not None else 'technical_only'}_passed")

    # ---- confidence helpers ----

    @staticmethod
    def _confidence_technical_only(t: float, thr: float) -> float:
        """
        Confidence при отсутствии AI: 0, если ниже порога;
        далее растёт до 1.0 примерно на +40 пунктов.
        """
        if t < thr:
            return 0.0
        excess = t - thr
        return float(min(1.0, 0.5 + (excess / 40.0)))

    def _confidence_fusion(self, t: float, a: float, combined: float, thr: float) -> float:
        """
        Confidence при наличии AI:
        - 0, если combined < thr
        - если оба >60 → быстрее растёт к 1.0
        - если смешанные → ограничиваем 0.8
        """
        if combined < thr:
            return 0.0

        tech_pos = t > 60.0
        ai_pos = a > 60.0
        excess = combined - thr

        if tech_pos and ai_pos:
            return float(min(1.0, 0.6 + (excess / 30.0)))
        if tech_pos or ai_pos:
            return float(min(0.8, 0.4 + (excess / 40.0)))
        return 0.3


# -------------------- legacy API --------------------

def pass_thresholds(
    ind_score: float,
    ai_score: Optional[float],
    regime: str,
    macro: Optional[dict] = None,  # reserved for compatibility
    thr: Optional[FusionConfig] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Legacy interface for threshold checking.

    Args:
        ind_score: Technical indicator score (0-100)
        ai_score: AI score (0-100) or None
        regime: regime name (supports: risk_on/risk_small/neutral/risk_off, bull/bear)
        macro: unused (kept for backward compatibility)
        thr: FusionConfig override

    Returns:
        (passed, metadata)
    """
    regime_state = _parse_regime_string(regime)

    fusion = SignalFusion(config=thr)
    signal = fusion.fuse_signals(
        technical_score=ind_score,
        ai_score=ai_score,
        regime=regime_state,
    )
    return signal.passed, signal.metadata


# -------------------- utils --------------------

def _clamp_0_100(x: Optional[float]) -> float:
    if x is None:
        return 0.0
    return float(max(0.0, min(100.0, x)))


def _parse_regime_string(name: str) -> RegimeState:
    """
    Расширенная поддержка строковых режимов.
    Понимает и краткие «bull/bear», и полные «risk_on/...».
    """
    n = (name or "").strip().lower()
    if n in ("risk_on", "bull"):
        return RegimeState.RISK_ON
    if n in ("risk_small", "small", "light"):
        return RegimeState.RISK_SMALL
    if n in ("risk_off", "bear"):
        return RegimeState.RISK_OFF
    return RegimeState.NEUTRAL


# -------------------- exports --------------------

__all__ = [
    "SignalDirection",
    "FusionConfig",
    "FusionSignal",
    "SignalFusion",
    "pass_thresholds",
]
