"""Spread cap risk rule.

Located in domain/risk/rules layer - monitors and limits bid-ask spread.
Prevents trading when spread is too wide, protecting from slippage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Union

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# ============== Types ==============

class RuleSeverity(Enum):
    """Risk rule severity levels."""

    INFO = "info"         # Informational only
    WARNING = "warning"   # Warning threshold
    CRITICAL = "critical" # Block trading


class RuleAction(Enum):
    """Actions that can be taken by risk rules."""

    ALLOW = "allow"              # Allow operation
    WARN = "warn"                # Allow with warning
    BLOCK = "block"              # Block operation
    REDUCE_SIZE = "reduce_size"  # Reduce position size


class SpreadType(Enum):
    """Types of spread calculation."""

    ABSOLUTE = "absolute"     # Absolute spread in quote currency
    PERCENTAGE = "percentage" # Percentage spread
    BPS = "bps"               # Basis points (1 bps = 0.01%)


# ============== Configuration ==============

@dataclass(frozen=True)
class SpreadCapConfig:
    """Configuration for spread cap rule."""

    # Base limit value; semantics depend on spread_type
    # For PERCENTAGE: percent value (e.g., 0.25 for 0.25%)
    # For BPS: basis points (e.g., 25 for 0.25%)
    # For ABSOLUTE: absolute quote-currency units (e.g., 5.0 USDT)
    max_spread_pct: float = 0.0

    # Warning threshold as percentage of max (0.8 = warn at 80% of limit)
    warning_threshold: float = 0.8

    # Spread type for calculation
    spread_type: SpreadType = SpreadType.PERCENTAGE

    # Different limits for different operations (override base)
    max_spread_entry_pct: Optional[float] = None  # For entries
    max_spread_exit_pct: Optional[float] = None   # For exits (usually more lenient)

    # Time-based adjustments
    allow_wider_spread_volatile: bool = True      # Allow wider spread in volatile markets
    volatility_multiplier: float = 1.5            # Multiply limit by this in volatile conditions

    # Minimum spread for alerts (too tight might indicate issues)
    # Interpreted in **percentage** terms
    min_spread_alert_pct: Optional[float] = None

    # Allow market orders even with wide spread (for emergencies)
    allow_emergency_orders: bool = True

    def is_enabled(self) -> bool:
        """Check if rule is enabled."""
        return float(self.max_spread_pct) > 0.0

    def get_warning_level(self) -> float:
        """Get warning threshold (ratio)."""
        return float(self.warning_threshold)

    def get_limit_for_operation(self, is_entry: bool) -> float:
        """Return the configured limit value (unconverted) for operation."""
        if is_entry and self.max_spread_entry_pct is not None:
            return float(self.max_spread_entry_pct)
        if not is_entry and self.max_spread_exit_pct is not None:
            return float(self.max_spread_exit_pct)
        return float(self.max_spread_pct)


# ============== Spread Provider Types ==============

SpreadProvider = Callable[[str], Optional[float]]
AsyncSpreadProvider = Callable[[str], Awaitable[Optional[float]]]
SpreadProviderUnion = Union[SpreadProvider, AsyncSpreadProvider]


# ============== Result Classes ==============

@dataclass
class SpreadMetrics:
    """Spread calculation metrics."""

    bid: Optional[Decimal]
    ask: Optional[Decimal]
    spread_absolute: Optional[Decimal]
    spread_pct: Optional[float]
    spread_bps: Optional[float]
    mid_price: Optional[Decimal]
    calculation_time: datetime
    is_volatile: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "bid": float(self.bid) if self.bid is not None else None,
            "ask": float(self.ask) if self.ask is not None else None,
            "spread_absolute": float(self.spread_absolute) if self.spread_absolute is not None else None,
            "spread_pct": self.spread_pct,
            "spread_bps": self.spread_bps,
            "mid_price": float(self.mid_price) if self.mid_price is not None else None,
            "calculation_time": self.calculation_time.isoformat(),
            "is_volatile": self.is_volatile,
        }


@dataclass
class RuleCheckResult:
    """Result of risk rule check."""

    action: RuleAction
    severity: RuleSeverity
    reason: str
    metrics: SpreadMetrics
    details: dict[str, Any]

    @property
    def is_blocked(self) -> bool:
        """Check if operation should be blocked."""
        return self.action == RuleAction.BLOCK

    @property
    def is_warning(self) -> bool:
        """Check if this is a warning."""
        return self.action == RuleAction.WARN

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "action": self.action.value,
            "severity": self.severity.value,
            "reason": self.reason,
            "metrics": self.metrics.to_dict(),
            "details": self.details,
        }


# ============== Main Rule ==============

class SpreadCapRule:
    """
    Spread cap risk rule.

    Monitors bid-ask spread and blocks trading when spread is too wide.
    Protects from excessive slippage and poor execution prices.

    Features:
    - Configurable spread limits
    - Different limits for entries vs exits
    - Warning thresholds
    - Volatility adjustments
    - Support for sync and async spread providers
    """

    def __init__(
        self,
        config: SpreadCapConfig,
        provider: Optional[SpreadProviderUnion] = None
    ):
        """
        Initialize spread cap rule.

        Args:
            config: Rule configuration
            provider: Function to get **current spread value** according to `spread_type`
                      (percentage for PERCENTAGE, bps for BPS, absolute units for ABSOLUTE).
        """
        self.config = config
        self.provider = provider
        self._spread_history: list[tuple[datetime, float]] = []
        self._max_history = 100

    async def check(
        self,
        symbol: str,
        is_entry: bool = True,
        is_emergency: bool = False,
        broker: Optional[Any] = None
    ) -> RuleCheckResult:
        """
        Check if spread is within acceptable limits.

        Args:
            symbol: Trading symbol
            is_entry: Whether this is an entry (True) or exit (False)
            is_emergency: Whether this is an emergency order
            broker: Optional broker for fetching ticker directly

        Returns:
            Rule check result with action and metrics
        """
        # Check if rule is enabled
        if not self.config.is_enabled():
            return self._create_disabled_result(symbol)

        # Allow emergency orders if configured
        if is_emergency and self.config.allow_emergency_orders:
            return self._create_emergency_allowed_result(symbol)

        # Get current spread
        metrics = await self._get_spread_metrics(symbol, broker)

        if metrics.spread_pct is None:
            # No spread data available (e.g., ABSOLUTE from provider but no mid/ticker)
            return self._create_no_data_result(symbol, metrics)

        # Update history
        self._update_spread_history(metrics.spread_pct)

        # Get applicable **percentage** limit (convert from ABSOLUTE/BPS if needed)
        limit_pct = self._effective_limit_pct(is_entry=is_entry, metrics=metrics)
        if limit_pct is None:
            # Can't convert limit without mid price — don't block
            return self._create_no_data_result(symbol, metrics)

        warning_limit_pct = limit_pct * self.config.get_warning_level()

        # Too tight spread alert (purely informational)
        if (self.config.min_spread_alert_pct is not None) and (metrics.spread_pct < self.config.min_spread_alert_pct):
            _log.warning(
                "spread_too_tight",
                extra={
                    "symbol": symbol,
                    "spread_pct": metrics.spread_pct,
                    "min_alert": self.config.min_spread_alert_pct,
                }
            )

        # Check spread against limits
        if metrics.spread_pct >= limit_pct:
            # Spread too wide - block
            return self._create_result(
                symbol=symbol,
                action=RuleAction.BLOCK,
                severity=RuleSeverity.CRITICAL,
                reason=f"Spread too wide: {metrics.spread_pct:.3f}% >= {limit_pct:.3f}%",
                metrics=metrics,
                is_entry=is_entry
            )

        if metrics.spread_pct >= warning_limit_pct:
            # Warning threshold
            return self._create_result(
                symbol=symbol,
                action=RuleAction.WARN,
                severity=RuleSeverity.WARNING,
                reason=f"Spread approaching limit: {metrics.spread_pct:.3f}% (limit: {limit_pct:.3f}%)",
                metrics=metrics,
                is_entry=is_entry
            )

        # Within limits
        return self._create_result(
            symbol=symbol,
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Spread within limits",
            metrics=metrics,
            is_entry=is_entry
        )

    # ---------- internals ----------

    async def _get_spread_metrics(
        self,
        symbol: str,
        broker: Optional[Any] = None
    ) -> SpreadMetrics:
        """Get current spread metrics (prefers provider, falls back to broker)."""
        bid: Optional[Decimal] = None
        ask: Optional[Decimal] = None
        mid_price: Optional[Decimal] = None
        spread_absolute: Optional[Decimal] = None
        spread_pct: Optional[float] = None

        # Try provider first
        provider_value: Optional[float] = None
        if self.provider:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(self.provider):
                    provider_value = await self.provider(symbol)  # type: ignore[arg-type]
                else:
                    provider_value = self.provider(symbol)  # type: ignore[call-arg]
            except Exception as e:
                _log.error(
                    "spread_provider_error",
                    exc_info=True,
                    extra={"symbol": symbol, "error": str(e)}
                )

        # If we got a provider value, interpret it per spread_type
        if provider_value is not None:
            if self.config.spread_type == SpreadType.PERCENTAGE:
                spread_pct = float(provider_value)
            elif self.config.spread_type == SpreadType.BPS:
                spread_pct = float(provider_value) / 100.0
            elif self.config.spread_type == SpreadType.ABSOLUTE:
                spread_absolute = dec(str(provider_value))
                # need mid price to convert to percent — fetch from broker if possible
                if broker:
                    try:
                        ticker = await broker.fetch_ticker(symbol)
                        if ticker:
                            bid = dec(str(ticker.get("bid", 0)))
                            ask = dec(str(ticker.get("ask", 0)))
                            if bid > 0 and ask > 0:
                                mid_price = (bid + ask) / 2
                    except Exception as e:
                        _log.error(
                            "broker_ticker_error",
                            exc_info=True,
                            extra={"symbol": symbol, "error": str(e)}
                        )
        # If still no pct, try direct broker path
        if spread_pct is None and broker:
            try:
                ticker = await broker.fetch_ticker(symbol)
                if ticker:
                    bid = dec(str(ticker.get("bid", 0)))
                    ask = dec(str(ticker.get("ask", 0)))
                    if bid > 0 and ask > 0:
                        spread_absolute = (ask - bid)
                        mid_price = (bid + ask) / 2
                        if mid_price > 0:
                            spread_pct = float((spread_absolute / mid_price) * 100)
            except Exception as e:
                _log.error(
                    "broker_ticker_error",
                    exc_info=True,
                    extra={"symbol": symbol, "error": str(e)}
                )

        # If provider gave absolute but we now have mid, convert to pct
        if (spread_pct is None) and (spread_absolute is not None) and (mid_price and mid_price > 0):
            try:
                spread_pct = float((spread_absolute / mid_price) * 100)
            except Exception:
                spread_pct = None

        # Derived bps
        spread_bps = (spread_pct * 100.0) if (spread_pct is not None) else None

        # Volatility check uses pct history
        is_volatile = self._check_volatility()

        return SpreadMetrics(
            bid=bid,
            ask=ask,
            spread_absolute=spread_absolute,
            spread_pct=spread_pct,
            spread_bps=spread_bps,
            mid_price=mid_price,
            calculation_time=datetime.now(timezone.utc),
            is_volatile=is_volatile
        )

    def _effective_limit_pct(self, is_entry: bool, metrics: SpreadMetrics) -> Optional[float]:
        """Convert configured limit to **percentage** for comparison, if possible."""
        base = self.config.get_limit_for_operation(is_entry)

        if self.config.spread_type == SpreadType.PERCENTAGE:
            return float(base)
        if self.config.spread_type == SpreadType.BPS:
            return float(base) / 100.0
        # ABSOLUTE → need mid_price to convert
        if metrics.mid_price and metrics.mid_price > 0:
            try:
                return float((dec(str(base)) / metrics.mid_price) * 100)
            except Exception:
                return None
        return None

    def _update_spread_history(self, spread_pct: float) -> None:
        """Update spread history for volatility calculation."""
        now = datetime.now(timezone.utc)
        self._spread_history.append((now, spread_pct))

        # Keep only recent history
        if len(self._spread_history) > self._max_history:
            self._spread_history = self._spread_history[-self._max_history:]

    def _check_volatility(self) -> bool:
        """Check if spread is volatile based on history."""
        if len(self._spread_history) < 10:
            return False

        # Calculate standard deviation of recent spreads
        recent_spreads = [s for _, s in self._spread_history[-20:]]
        if not recent_spreads:
            return False

        mean = sum(recent_spreads) / len(recent_spreads)
        if mean <= 0:
            return False

        variance = sum((s - mean) ** 2 for s in recent_spreads) / len(recent_spreads)
        std_dev = variance ** 0.5

        # Consider volatile if std dev > 50% of mean
        return std_dev > mean * 0.5

    def _create_result(
        self,
        symbol: str,
        action: RuleAction,
        severity: RuleSeverity,
        reason: str,
        metrics: SpreadMetrics,
        is_entry: bool = True
    ) -> RuleCheckResult:
        """Create rule check result."""
        details = {
            "limit_pct_effective": self._effective_limit_pct(is_entry, metrics),
            "warning_ratio": self.config.get_warning_level(),
            "is_entry": is_entry,
            "spread_type": self.config.spread_type.value,
            "volatility_adjusted": metrics.is_volatile,
        }

        # Log based on severity
        log_extra = {
            "symbol": symbol,
            "action": action.value,
            "spread_pct": metrics.spread_pct,
            "limit_pct": details["limit_pct_effective"],
        }

        if severity == RuleSeverity.CRITICAL:
            _log.warning("spread_cap_exceeded", extra=log_extra)
        elif severity == RuleSeverity.WARNING:
            _log.info("spread_cap_warning", extra=log_extra)
        else:
            _log.debug("spread_cap_check", extra=log_extra)

        return RuleCheckResult(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            details=details
        )

    def _create_disabled_result(self, symbol: str) -> RuleCheckResult:
        """Create result for disabled rule."""
        metrics = SpreadMetrics(
            bid=None,
            ask=None,
            spread_absolute=None,
            spread_pct=None,
            spread_bps=None,
            mid_price=None,
            calculation_time=datetime.now(timezone.utc),
            is_volatile=False
        )

        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Rule disabled",
            metrics=metrics,
            details={"max_spread": 0.0, "symbol": symbol}
        )

    def _create_no_data_result(self, symbol: str, metrics: SpreadMetrics) -> RuleCheckResult:
        """Create result when no spread data available."""
        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="No spread data available",
            metrics=metrics,
            details={"data_available": False, "symbol": symbol}
        )

    def _create_emergency_allowed_result(self, symbol: str) -> RuleCheckResult:
        """Create result for emergency orders."""
        metrics = SpreadMetrics(
            bid=None,
            ask=None,
            spread_absolute=None,
            spread_pct=None,
            spread_bps=None,
            mid_price=None,
            calculation_time=datetime.now(timezone.utc),
            is_volatile=False
        )

        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Emergency order allowed",
            metrics=metrics,
            details={"is_emergency": True, "symbol": symbol}
        )


# ============== Factory Function ==============

def create_spread_cap_rule(
    settings: Any,
    provider: Optional[SpreadProviderUnion] = None
) -> SpreadCapRule:
    """
    Factory function to create spread cap rule from settings.

    Args:
        settings: Application settings
        provider: Optional spread provider function (value semantics depend on RISK_SPREAD_TYPE)

    Returns:
        Configured SpreadCapRule
    """
    # Determine spread type
    spread_type_str = getattr(settings, "RISK_SPREAD_TYPE", "percentage")
    spread_type = SpreadType.PERCENTAGE
    try:
        spread_type = SpreadType(str(spread_type_str).lower())
    except ValueError:
        pass

    config = SpreadCapConfig(
        max_spread_pct=float(getattr(settings, "RISK_MAX_SPREAD_PCT", 0.0)),
        warning_threshold=float(getattr(settings, "RISK_SPREAD_WARNING_THRESHOLD", 0.8)),
        spread_type=spread_type,
        max_spread_entry_pct=getattr(settings, "RISK_MAX_SPREAD_ENTRY_PCT", None),
        max_spread_exit_pct=getattr(settings, "RISK_MAX_SPREAD_EXIT_PCT", None),
        allow_wider_spread_volatile=bool(getattr(settings, "RISK_ALLOW_WIDER_SPREAD_VOLATILE", True)),
        volatility_multiplier=float(getattr(settings, "RISK_SPREAD_VOLATILITY_MULTIPLIER", 1.5)),
        min_spread_alert_pct=getattr(settings, "RISK_MIN_SPREAD_ALERT_PCT", None),
        allow_emergency_orders=bool(getattr(settings, "RISK_ALLOW_EMERGENCY_ORDERS", True))
    )

    return SpreadCapRule(config, provider)
