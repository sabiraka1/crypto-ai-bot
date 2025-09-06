"""
Market regime types and data structures.

According to README, we have 4 regime states:
- risk_on: score > 0.5 (full position size)
- risk_small: 0 < score ≤ 0.5 (50% of FIXED_AMOUNT)
- neutral: -0.5 ≤ score ≤ 0 (only exits, no entries)
- risk_off: score < -0.5 (full blocking)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from crypto_ai_bot.utils.decimal import dec


# ---------- helpers ----------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------- regime enum ----------

class RegimeState(Enum):
    """
    Market regime states based on macro score.

    Determines position sizing and entry permissions.
    """
    RISK_ON = "risk_on"          # score > 0.5, full size
    RISK_SMALL = "risk_small"    # 0 < score <= 0.5, 50% size
    NEUTRAL = "neutral"          # -0.5 ≤ score ≤ 0, exits only
    RISK_OFF = "risk_off"        # score < -0.5, no new trades

    @classmethod
    def from_score(cls, score: float) -> "RegimeState":
        """Convert numeric score to regime state with README-aligned boundaries."""
        if score > 0.5:
            return cls.RISK_ON
        elif score > 0.0:  # 0 < score ≤ 0.5
            return cls.RISK_SMALL
        elif score >= -0.5:  # -0.5 ≤ score ≤ 0
            return cls.NEUTRAL
        else:  # score < -0.5
            return cls.RISK_OFF

    def allows_entry(self) -> bool:
        """Check if regime allows new entries."""
        return self in (self.RISK_ON, self.RISK_SMALL)

    def allows_exit(self) -> bool:
        """Check if regime allows exits (always true)."""
        return True

    def position_size_multiplier(self) -> Decimal:
        """Get position size multiplier for this regime (Decimal)."""
        if self is self.RISK_ON:
            return dec("1.0")
        if self is self.RISK_SMALL:
            return dec("0.5")
        return dec("0.0")


# Type alias for backward compatibility
Regime = Literal["risk_on", "risk_small", "neutral", "risk_off"]


# ---------- macro snapshot ----------

@dataclass(frozen=True)
class MacroSnapshot:
    """
    Snapshot of macro market indicators.
    Used to calculate regime score.
    """
    # DXY (Dollar Index) - negative correlation with crypto
    dxy_value: Optional[float] = None
    dxy_change_pct: Optional[float] = None
    dxy_updated_at: Optional[datetime] = None

    # BTC Dominance - affects alt season
    btc_dom_value: Optional[float] = None
    btc_dom_change_pct: Optional[float] = None
    btc_dom_updated_at: Optional[datetime] = None

    # FOMC events - market uncertainty
    fomc_event_today: bool = False
    fomc_hours_until: Optional[int] = None
    fomc_hours_since: Optional[int] = None

    # Calculated score and state
    score: Optional[float] = None
    state: Optional[RegimeState] = None
    timestamp: Optional[datetime] = None

    def calculate_score(
        self,
        dxy_weight: float = 0.35,
        btc_dom_weight: float = 0.35,
        fomc_weight: float = 0.30,
    ) -> float:
        """
        Calculate regime score from indicators.

        Returns:
            Score from -1.0 to 1.0
            Positive = risk on, Negative = risk off
        """
        # weights are expected to sum to ~1.0; tolerate small drift
        w_dxy = _clamp(dxy_weight, 0.0, 1.0)
        w_btc = _clamp(btc_dom_weight, 0.0, 1.0)
        w_fomc = _clamp(fomc_weight, 0.0, 1.0)
        total_w = w_dxy + w_btc + w_fomc
        if 0.99 <= total_w <= 1.01:
            # normalize softly to avoid gradual drift
            w_dxy /= total_w
            w_btc /= total_w
            w_fomc /= total_w

        score = 0.0

        # DXY component (inverted - high DXY bad for crypto)
        if self.dxy_change_pct is not None:
            dxy_score = _clamp(-self.dxy_change_pct / 100.0, -1.0, 1.0)
            score += dxy_score * w_dxy

        # BTC Dominance component (high dominance bad for alts)
        if self.btc_dom_change_pct is not None:
            btc_score = _clamp(-self.btc_dom_change_pct / 100.0, -1.0, 1.0)
            score += btc_score * w_btc

        # FOMC component (events create uncertainty)
        if self.fomc_event_today:
            score -= w_fomc  # maximum negative impact
        elif self.fomc_hours_until is not None and self.fomc_hours_until <= 8:
            # Approaching FOMC - gradual risk reduction (linear ramp to -1.0)
            ramp = 1 - (self.fomc_hours_until / 8.0)
            score += (-1.0 * ramp) * w_fomc
        elif self.fomc_hours_since is not None and self.fomc_hours_since <= 4:
            # Just after FOMC - still risky (half magnitude)
            ramp = 1 - (self.fomc_hours_since / 4.0)
            score += (-0.5 * ramp) * w_fomc

        return _clamp(score, -1.0, 1.0)

    def resolve_state(
        self,
        *,
        dxy_weight: float = 0.35,
        btc_dom_weight: float = 0.35,
        fomc_weight: float = 0.30,
        set_timestamp: bool = True,
    ) -> "MacroSnapshot":
        """
        Compute score and state, returning a (frozen) dataclass copy with fields set.
        """
        s = self.calculate_score(dxy_weight, btc_dom_weight, fomc_weight)
        st = RegimeState.from_score(s)
        ts = datetime.now(timezone.utc) if set_timestamp else self.timestamp
        return replace(self, score=s, state=st, timestamp=ts)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/events."""
        return {
            "dxy_value": self.dxy_value,
            "dxy_change_pct": self.dxy_change_pct,
            "dxy_updated_at": self.dxy_updated_at.isoformat() if self.dxy_updated_at else None,
            "btc_dom_value": self.btc_dom_value,
            "btc_dom_change_pct": self.btc_dom_change_pct,
            "btc_dom_updated_at": self.btc_dom_updated_at.isoformat() if self.btc_dom_updated_at else None,
            "fomc_event_today": self.fomc_event_today,
            "fomc_hours_until": self.fomc_hours_until,
            "fomc_hours_since": self.fomc_hours_since,
            "score": self.score,
            "state": self.state.value if self.state else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# ---------- config ----------

@dataclass(frozen=True)
class RegimeConfig:
    """Configuration for regime detection."""
    # Score thresholds
    risk_on_threshold: float = 0.5
    risk_small_threshold: float = 0.0
    neutral_threshold: float = -0.5

    # Component weights (should sum to ~1.0)
    dxy_weight: float = 0.35
    btc_dom_weight: float = 0.35
    fomc_weight: float = 0.30

    # Change thresholds (percent)
    dxy_significant_change: float = 0.35
    btc_dom_significant_change: float = 0.60

    # FOMC timings (hours)
    fomc_block_hours_before: int = 8
    fomc_block_hours_after: int = 4

    # Update frequency
    update_interval_sec: int = 300  # 5 minutes

    def validate(self) -> None:
        """Validate configuration (raises AssertionError on invalid config)."""
        assert -1.0 <= self.neutral_threshold < self.risk_small_threshold < self.risk_on_threshold <= 1.0
        for w in (self.dxy_weight, self.btc_dom_weight, self.fomc_weight):
            assert 0.0 <= w <= 1.0
        assert abs((self.dxy_weight + self.btc_dom_weight + self.fomc_weight) - 1.0) < 0.01
        assert self.update_interval_sec > 0


__all__ = [
    "RegimeState",
    "Regime",
    "MacroSnapshot",
    "RegimeConfig",
]
