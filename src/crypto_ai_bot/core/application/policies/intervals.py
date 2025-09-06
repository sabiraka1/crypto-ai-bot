"""Background process intervals and policies.

Located in application/policies layer - defines timing policies for background processes.
Supports environment overrides and adaptive adjustments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Iterable, Dict

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# ============== Helpers ==============

def _coerce_int(value: Any, *, default: int) -> int:
    """Safely coerce any value to int, returning default on failure."""
    try:
        # allow floats and numeric strings, but store as int seconds
        return int(float(value))
    except Exception:
        return default


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


# ============== Base Intervals ==============

@dataclass(frozen=True)
class IntervalConfig:
    """Configuration for a single interval."""

    name: str
    default_sec: int
    min_sec: int
    max_sec: int
    env_var: Optional[str] = None
    adaptive: bool = False

    def _normalized_bounds(self) -> tuple[int, int]:
        """Ensure min/max are consistent; auto-fix if misconfigured."""
        if self.min_sec <= self.max_sec:
            return self.min_sec, self.max_sec
        _log.warning(
            "interval_bounds_swapped",
            extra={"name": self.name, "min": self.min_sec, "max": self.max_sec},
        )
        return self.max_sec, self.min_sec

    def _from_env(self) -> Optional[int]:
        """Read value from environment, if configured."""
        if not self.env_var:
            return None
        raw = os.getenv(self.env_var)
        if raw is None:
            return None

        v = _coerce_int(raw, default=self.default_sec)
        lo, hi = self._normalized_bounds()
        if v < lo:
            _log.warning(
                "interval_below_minimum",
                extra={"name": self.name, "value": v, "min": lo},
            )
            return lo
        if v > hi:
            _log.warning(
                "interval_above_maximum",
                extra={"name": self.name, "value": v, "max": hi},
            )
            return hi
        return v

    def _from_settings(self, settings: Optional[Any]) -> Optional[int]:
        """Read value from settings.<NAME> or settings.<NAME>_SEC (both supported)."""
        if not settings:
            return None

        # ORCHESTRATOR_CYCLE, SIGNAL_GENERATION, ...
        key_plain = self.name.upper()
        # ORCHESTRATOR_CYCLE_SEC, SIGNAL_GENERATION_SEC, ...
        key_sec = f"{key_plain}_SEC"

        if hasattr(settings, key_plain):
            return _clamp(_coerce_int(getattr(settings, key_plain), default=self.default_sec), *self._normalized_bounds())
        if hasattr(settings, key_sec):
            return _clamp(_coerce_int(getattr(settings, key_sec), default=self.default_sec), *self._normalized_bounds())

        return None

    def get_value(self, settings: Optional[Any] = None) -> int:
        """Get interval value with overrides (ENV → settings → default)."""
        lo, hi = self._normalized_bounds()

        # 1) ENV has top priority
        env_val = self._from_env()
        if env_val is not None:
            return env_val

        # 2) Settings
        st_val = self._from_settings(settings)
        if st_val is not None:
            return st_val

        # 3) Default
        return _clamp(self.default_sec, lo, hi)


# ============== Process Intervals ==============

class ProcessIntervals:
    """
    Intervals for all background processes.

    Each interval can be overridden via environment variables and/or settings.
    Supports adaptive adjustments based on system load.
    """

    # ===== Core Trading Processes =====

    ORCHESTRATOR_CYCLE = IntervalConfig(
        name="orchestrator_cycle",
        default_sec=15,  # Main trading cycle - 15 seconds
        min_sec=5,
        max_sec=60,
        env_var="ORCHESTRATOR_CYCLE_SEC",
        adaptive=True,  # Can be adjusted based on market conditions
    )

    SIGNAL_GENERATION = IntervalConfig(
        name="signal_generation",
        default_sec=15,  # Generate signals every 15 seconds
        min_sec=5,
        max_sec=300,
        env_var="SIGNAL_GENERATION_SEC",
        adaptive=True,
    )

    # ===== Risk & Protection =====

    PROTECTIVE_EXITS_CHECK = IntervalConfig(
        name="protective_exits_check",
        default_sec=5,  # Check stop-losses frequently
        min_sec=1,
        max_sec=30,
        env_var="PROTECTIVE_EXITS_CHECK_SEC",
        adaptive=False,  # Critical - fixed interval
    )

    RISK_COUNTERS_RESET = IntervalConfig(
        name="risk_counters_reset",
        default_sec=86400,  # Daily reset (24 hours)
        min_sec=3600,
        max_sec=604800,
        env_var="RISK_COUNTERS_RESET_SEC",
        adaptive=False,
    )

    # ===== Reconciliation & Settlement =====

    RECONCILIATION = IntervalConfig(
        name="reconciliation",
        default_sec=60,  # Reconcile with exchange every minute
        min_sec=30,
        max_sec=300,
        env_var="RECONCILIATION_SEC",
        adaptive=True,
    )

    SETTLEMENT = IntervalConfig(
        name="settlement",
        default_sec=30,  # Check partial fills every 30 seconds
        min_sec=10,
        max_sec=120,
        env_var="SETTLEMENT_SEC",
        adaptive=True,
    )

    # ===== Health & Monitoring =====

    HEALTH_CHECK = IntervalConfig(
        name="health_check",
        default_sec=10,  # Health check every 10 seconds
        min_sec=5,
        max_sec=60,
        env_var="HEALTH_CHECK_SEC",
        adaptive=False,
    )

    WATCHDOG = IntervalConfig(
        name="watchdog",
        default_sec=3,  # Watchdog ping every 3 seconds
        min_sec=1,
        max_sec=10,
        env_var="WATCHDOG_SEC",
        adaptive=False,  # Critical - fixed interval
    )

    METRICS_COLLECTION = IntervalConfig(
        name="metrics_collection",
        default_sec=15,  # Collect metrics every 15 seconds
        min_sec=5,
        max_sec=60,
        env_var="METRICS_COLLECTION_SEC",
        adaptive=True,
    )

    # ===== Market Data =====

    TICKER_UPDATE = IntervalConfig(
        name="ticker_update",
        default_sec=5,  # Update ticker every 5 seconds
        min_sec=1,
        max_sec=30,
        env_var="TICKER_UPDATE_SEC",
        adaptive=True,
    )

    OHLCV_FETCH = IntervalConfig(
        name="ohlcv_fetch",
        default_sec=60,  # Fetch OHLCV every minute
        min_sec=15,
        max_sec=300,
        env_var="OHLCV_FETCH_SEC",
        adaptive=True,
    )

    REGIME_UPDATE = IntervalConfig(
        name="regime_update",
        default_sec=300,  # Update market regime every 5 minutes
        min_sec=60,
        max_sec=3600,
        env_var="REGIME_UPDATE_SEC",
        adaptive=True,
    )

    # ===== Maintenance =====

    DATABASE_BACKUP = IntervalConfig(
        name="database_backup",
        default_sec=86400,  # Daily backup
        min_sec=3600,
        max_sec=604800,
        env_var="DATABASE_BACKUP_SEC",
        adaptive=False,
    )

    LOG_ROTATION = IntervalConfig(
        name="log_rotation",
        default_sec=86400,  # Daily rotation
        min_sec=3600,
        max_sec=604800,
        env_var="LOG_ROTATION_SEC",
        adaptive=False,
    )

    CLEANUP = IntervalConfig(
        name="cleanup",
        default_sec=3600,  # Hourly cleanup
        min_sec=600,
        max_sec=86400,
        env_var="CLEANUP_SEC",
        adaptive=False,
    )

    # ---- iteration helpers ----
    @classmethod
    def iter_all(cls) -> Iterable[IntervalConfig]:
        """Iterate over all IntervalConfig attributes."""
        for k, v in cls.__dict__.items():
            if isinstance(v, IntervalConfig):
                yield v


# ============== Adaptive Interval Manager ==============

class AdaptiveIntervalManager:
    """
    Manages adaptive interval adjustments based on system conditions.

    Adjusts intervals based on:
    - Market volatility
    - System load
    - Error rates
    - Trading activity
    """

    def __init__(self, base_intervals: ProcessIntervals):
        self.base_intervals = base_intervals
        self.adjustments: Dict[str, float] = {}
        self.conditions: Dict[str, Any] = {}

    def update_conditions(
        self,
        volatility: Optional[float] = None,
        cpu_usage: Optional[float] = None,
        error_rate: Optional[float] = None,
        trades_per_hour: Optional[int] = None,
    ) -> None:
        """Update system conditions for adaptive adjustments."""
        if volatility is not None:
            self.conditions["volatility"] = float(volatility)
        if cpu_usage is not None:
            self.conditions["cpu_usage"] = float(cpu_usage)
        if error_rate is not None:
            self.conditions["error_rate"] = float(error_rate)
        if trades_per_hour is not None:
            self.conditions["trades_per_hour"] = int(trades_per_hour)

        # Recalculate adjustments
        self._calculate_adjustments()

    def _calculate_adjustments(self) -> None:
        """Calculate interval adjustments based on conditions."""
        # reset old adjustments so they don't accumulate across condition changes
        self.adjustments.clear()

        # High/low volatility → adjust market-related frequency
        volatility = self.conditions.get("volatility")
        if volatility is not None:
            if volatility > 2.0:  # High volatility (e.g., ATR% > 2)
                self.adjustments["signal_generation"] = 0.5  # 50% faster
                self.adjustments["ticker_update"] = 0.5
                self.adjustments["protective_exits_check"] = 0.7
            elif volatility < 0.5:  # Low volatility
                self.adjustments["signal_generation"] = 1.5  # 50% slower
                self.adjustments["ticker_update"] = 2.0

        # High CPU → reduce frequency of heavy tasks
        cpu_usage = self.conditions.get("cpu_usage")
        if cpu_usage is not None:
            if cpu_usage > 80.0:
                self.adjustments["metrics_collection"] = 2.0
                self.adjustments["ohlcv_fetch"] = 1.5
            elif cpu_usage < 20.0:
                self.adjustments["metrics_collection"] = 0.8

        # High error rate → slow main loops, speed reconciliation
        error_rate = self.conditions.get("error_rate")
        if error_rate is not None and error_rate > 0.1:  # >10% errors
            self.adjustments["orchestrator_cycle"] = 2.0
            self.adjustments["reconciliation"] = 0.5  # more frequent checks

        # Activity-aware settlement/reconcile cadence
        trades = self.conditions.get("trades_per_hour")
        if trades is not None:
            if trades < 1:
                self.adjustments["settlement"] = 2.0
                self.adjustments["reconciliation"] = 1.5
            elif trades > 10:
                self.adjustments["settlement"] = 0.5
                self.adjustments["reconciliation"] = 0.7

    def get_adjusted_interval(self, interval: IntervalConfig, settings: Optional[Any] = None) -> int:
        """Get adjusted interval value (clamped)."""
        base_value = interval.get_value(settings)
        if not interval.adaptive:
            return base_value

        factor = float(self.adjustments.get(interval.name, 1.0))
        lo, hi = interval._normalized_bounds()

        # round to nearest int second (instead of truncating down)
        adjusted = int(round(base_value * factor))
        adjusted = _clamp(adjusted, lo, hi)

        if adjusted != base_value:
            _log.debug(
                "interval_adjusted",
                extra={"name": interval.name, "base": base_value, "adjusted": adjusted, "factor": factor},
            )

        return adjusted


# ============== Legacy Compatibility ==============

class BackgroundIntervals:
    """
    Legacy compatibility class.

    Provides backward compatibility with old code that expects simple attributes.
    """

    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings
        self.intervals = ProcessIntervals()

    @property
    def RECONCILE_SEC(self) -> int:
        """Reconciliation interval."""
        return self.intervals.RECONCILIATION.get_value(self.settings)

    @property
    def SETTLEMENT_SEC(self) -> int:
        """Settlement interval."""
        return self.intervals.SETTLEMENT.get_value(self.settings)

    @property
    def WATCHDOG_SEC(self) -> int:
        """Watchdog interval."""
        return self.intervals.WATCHDOG.get_value(self.settings)

    @property
    def HEALTH_CHECK_SEC(self) -> int:
        """Health check interval."""
        return self.intervals.HEALTH_CHECK.get_value(self.settings)


# ============== Factory Functions ==============

def get_intervals(settings: Optional[Any] = None) -> ProcessIntervals:
    """Get process intervals (class-style container)."""
    # settings kept for API symmetry; not used directly here
    return ProcessIntervals()


def get_adaptive_manager(settings: Optional[Any] = None) -> AdaptiveIntervalManager:
    """Get adaptive interval manager bound to base intervals."""
    intervals = get_intervals(settings)
    return AdaptiveIntervalManager(intervals)


def get_legacy_intervals(settings: Optional[Any] = None) -> BackgroundIntervals:
    """Get legacy-compatible intervals facade."""
    return BackgroundIntervals(settings)


__all__ = [
    "IntervalConfig",
    "ProcessIntervals",
    "AdaptiveIntervalManager",
    "BackgroundIntervals",
    "get_intervals",
    "get_adaptive_manager",
    "get_legacy_intervals",
]
