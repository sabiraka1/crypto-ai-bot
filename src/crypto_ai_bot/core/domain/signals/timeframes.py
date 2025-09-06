"""
Timeframe weights for multi-timeframe analysis.

Supports both static and adaptive weight calculation based on market conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Mapping, Iterable

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)

# canonical order of timeframes we support here
_TF_ORDER: tuple[str, ...] = ("15m", "1h", "4h", "1d", "1w")


def _clamp01(x: float) -> float:
    """Clamp value to [0, 1] range."""
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass(frozen=True)
class TFWeights:
    """
    Weights for multi-timeframe aggregation.

    Default weights prioritize shorter timeframes for trading signals
    while using longer timeframes for trend confirmation.
    """

    w_15m: float = 0.40  # Main trading timeframe
    w_1h: float = 0.25   # Short-term trend
    w_4h: float = 0.20   # Medium-term trend
    w_1d: float = 0.10   # Daily trend
    w_1w: float = 0.05   # Weekly trend

    def __post_init__(self) -> None:
        """Validate weights on creation."""
        # Non-negativity
        for w in self.as_tuple():
            if w < 0.0:
                raise ValueError("All timeframe weights must be non-negative")

        # Soft check: warn if not close to 1.0 (but do not fail)
        total = self.total()
        if total > 0 and abs(total - 1.0) > 0.01:
            _log.warning(
                "timeframe_weights_sum_not_one",
                extra={"total": round(total, 6), "hint": "call normalized()"},
            )

    # ---- accessors ---------------------------------------------------

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        """Get weights as tuple (15m, 1h, 4h, 1d, 1w)."""
        return (self.w_15m, self.w_1h, self.w_4h, self.w_1d, self.w_1w)

    def as_dict(self) -> dict[str, float]:
        """Get weights as dictionary with timeframe keys."""
        return {
            "15m": self.w_15m,
            "1h": self.w_1h,
            "4h": self.w_4h,
            "1d": self.w_1d,
            "1w": self.w_1w,
        }

    def total(self) -> float:
        """Sum of all weights (should be ~1.0)."""
        return float(self.w_15m + self.w_1h + self.w_4h + self.w_1d + self.w_1w)

    # ---- transforms --------------------------------------------------

    def normalized(self, *, eps: float = 1e-12) -> TFWeights:
        """
        Return new weights normalized to sum exactly to 1.0.

        - If the sum is ~0, fallback to equal distribution.
        - Keeps numeric stability with `eps`.
        """
        total = self.total()
        if total <= eps:
            _log.warning("timeframe_weights_zero_total_equal_fallback")
            return TFWeights(w_15m=0.2, w_1h=0.2, w_4h=0.2, w_1d=0.2, w_1w=0.2)

        if abs(total - 1.0) < eps:
            return self

        d = self.as_dict()
        return TFWeights(
            w_15m=d["15m"] / total,
            w_1h=d["1h"] / total,
            w_4h=d["4h"] / total,
            w_1d=d["1d"] / total,
            w_1w=d["1w"] / total,
        )

    def clamped01(self) -> TFWeights:
        """Return new weights with each component clamped to [0, 1]."""
        d = self.as_dict()
        return TFWeights(
            w_15m=_clamp01(d["15m"]),
            w_1h=_clamp01(d["1h"]),
            w_4h=_clamp01(d["4h"]),
            w_1d=_clamp01(d["1d"]),
            w_1w=_clamp01(d["1w"]),
        )

    def blend(self, other: TFWeights, alpha: float) -> TFWeights:
        """
        Linearly blend two TFWeights:  (1 - alpha)*self + alpha*other.

        Args:
            other: weights to blend in
            alpha: mix factor in [0, 1]
        """
        a = _clamp01(alpha)
        d1, d2 = self.as_dict(), other.as_dict()
        return TFWeights(
            w_15m=(1 - a) * d1["15m"] + a * d2["15m"],
            w_1h=(1 - a) * d1["1h"] + a * d2["1h"],
            w_4h=(1 - a) * d1["4h"] + a * d2["4h"],
            w_1d=(1 - a) * d1["1d"] + a * d2["1d"],
            w_1w=(1 - a) * d1["1w"] + a * d2["1w"],
        )

    # ---- aggregations ------------------------------------------------

    def weighted_average(self, values: Mapping[str, float]) -> float:
        """
        Calculate weighted average over provided timeframe values.

        Missing keys are ignored silently; if all keys are missing → 0.0
        """
        if not values:
            return 0.0

        acc = 0.0
        wsum = 0.0
        for tf, w in self.as_dict().items():
            if tf in values:
                acc += w * float(values[tf])
                wsum += w

        # If none of our keys present — return 0 to avoid division by small wsum
        if wsum <= 0.0:
            return 0.0
        # Weights already embedded in acc; do not divide by wsum
        return acc

    # ---- convenience -------------------------------------------------

    @classmethod
    def from_mapping(cls, data: Mapping[str, float], *, normalize: bool = True) -> TFWeights:
        """
        Construct TFWeights from mapping like {"15m": 0.4, "1h": 0.25, ...}.

        Unknown keys are ignored. Missing keys default to 0.0.
        """
        d = {k: float(data.get(k, 0.0)) for k in _TF_ORDER}
        w = cls(w_15m=d["15m"], w_1h=d["1h"], w_4h=d["4h"], w_1d=d["1d"], w_1w=d["1w"])
        return w.normalized() if normalize else w


class AdaptiveTimeframeWeights:
    """
    Adaptive weight calculator that adjusts based on market conditions.

    Higher volatility on a timeframe → higher weight for that timeframe.
    This helps capture more signal during active market periods.
    """

    def __init__(
        self,
        base_weights: Optional[TFWeights] = None,
        volatility_factor: float = 0.3,
    ):
        """
        Initialize adaptive weight calculator.

        Args:
            base_weights: Base weights to adapt from
            volatility_factor: How much volatility affects weights (0..1)
        """
        self.base_weights = (base_weights or TFWeights()).clamped01().normalized()
        self.volatility_factor = _clamp01(volatility_factor)

        _log.info(
            "adaptive_timeframe_weights_init",
            extra={
                "base_weights": self.base_weights.as_dict(),
                "volatility_factor": self.volatility_factor,
            },
        )

    def calculate_weights(
        self,
        atr_values: Mapping[str, float],
        normalize: bool = True,
    ) -> TFWeights:
        """
        Calculate adaptive weights based on ATR (volatility) values.

        Args:
            atr_values: ATR values by timeframe {"15m": 0.5, "1h": 0.8, ...}
            normalize: Whether to normalize weights to sum to 1.0

        Returns:
            Adapted TFWeights
        """
        if not atr_values:
            return self.base_weights

        base = self.base_weights.as_dict()

        # Sum ATR only over known timeframes
        total_atr = sum(float(atr_values.get(tf, 0.0)) for tf in _TF_ORDER)
        if total_atr <= 0.0:
            return self.base_weights

        adapted: dict[str, float] = {}
        for tf, b in base.items():
            atr_ratio = float(atr_values.get(tf, 0.0)) / total_atr
            # Blend: more volatile TF gets more weight
            final_w = (b * (1.0 - self.volatility_factor)) + (atr_ratio * self.volatility_factor)
            adapted[tf] = final_w

        w = TFWeights.from_mapping(adapted, normalize=False).clamped01()
        return w.normalized() if normalize else w

    def calculate_trend_aligned_weights(
        self,
        trend_scores: Mapping[str, float],
        normalize: bool = True,
    ) -> TFWeights:
        """
        Adjust weights based on trend alignment scores.

        Stronger trends on a timeframe → higher weight.

        Args:
            trend_scores: Trend strength by timeframe (-1 to 1)
            normalize: Whether to normalize weights

        Returns:
            Trend-aligned weights
        """
        if not trend_scores:
            return self.base_weights

        base = self.base_weights.as_dict()
        adapted: dict[str, float] = {}

        for tf, b in base.items():
            # Map trend score (-1..1) to multiplier (0.5..1.5)
            score = float(trend_scores.get(tf, 0.0))
            multiplier = 1.0 + max(-1.0, min(1.0, score)) * 0.5
            adapted[tf] = b * multiplier

        w = TFWeights.from_mapping(adapted, normalize=False).clamped01()
        return w.normalized() if normalize else w


# Preset weight configurations
class WeightPresets:
    """Common weight presets for different market conditions."""

    # Scalping - focus on very short term
    SCALPING = TFWeights(
        w_15m=0.60,
        w_1h=0.25,
        w_4h=0.10,
        w_1d=0.04,
        w_1w=0.01,
    )

    # Day trading - balanced short to medium term
    DAY_TRADING = TFWeights(
        w_15m=0.40,
        w_1h=0.25,
        w_4h=0.20,
        w_1d=0.10,
        w_1w=0.05,
    )

    # Swing trading - focus on medium to long term
    SWING_TRADING = TFWeights(
        w_15m=0.20,
        w_1h=0.25,
        w_4h=0.30,
        w_1d=0.20,
        w_1w=0.05,
    )

    # Position trading - long term focus
    POSITION_TRADING = TFWeights(
        w_15m=0.10,
        w_1h=0.15,
        w_4h=0.25,
        w_1d=0.30,
        w_1w=0.20,
    )

    # Equal weights - no preference
    EQUAL = TFWeights(
        w_15m=0.20,
        w_1h=0.20,
        w_4h=0.20,
        w_1d=0.20,
        w_1w=0.20,
    )

    @classmethod
    def get_preset(cls, name: str) -> TFWeights:
        """
        Get preset by name.

        Args:
            name: Preset name (case-insensitive)

        Returns:
            TFWeights preset or default DAY_TRADING
        """
        key = name.upper().replace(" ", "_")
        presets = {
            "SCALPING": cls.SCALPING,
            "DAY_TRADING": cls.DAY_TRADING,
            "SWING_TRADING": cls.SWING_TRADING,
            "POSITION_TRADING": cls.POSITION_TRADING,
            "EQUAL": cls.EQUAL,
        }
        return presets.get(key, cls.DAY_TRADING)


# Export
__all__ = [
    "TFWeights",
    "AdaptiveTimeframeWeights",
    "WeightPresets",
]
