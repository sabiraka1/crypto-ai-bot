"""Daily loss limit risk rule.

Located in domain/risk/rules layer - enforces daily loss limits.
Blocks trading when daily realized PnL reaches configured threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Callable, Awaitable, Iterable

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# ============== helpers ==============

async def _maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call function that might be sync or async."""
    res = fn(*args, **kwargs)
    if hasattr(res, "__await__"):
        return await res  # type: ignore[func-returns-value]
    return res


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Tolerant attribute/key getter."""
    if obj is None:
        return default
    if hasattr(obj, name):
        try:
            return getattr(obj, name)
        except Exception:
            return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


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


# ============== Configuration ==============

@dataclass(frozen=True)
class DailyLossConfig:
    """Configuration for daily loss limit rule."""

    # Maximum daily loss in quote currency (0 = disabled)
    limit_quote: Decimal = Decimal("0")

    # Warning threshold as percentage of limit (0.8 = warn at 80% of limit)
    warning_threshold: float = 0.8

    # Whether to include fees in PnL calculation
    include_fees: bool = True

    # Whether to include unrealized PnL
    include_unrealized: bool = False

    # Custom reset time (hour in UTC, None = midnight)
    reset_hour_utc: Optional[int] = None

    # Whether to allow closing positions after limit hit
    allow_closes_after_limit: bool = True

    def is_enabled(self) -> bool:
        """Check if rule is enabled."""
        return self.limit_quote > 0

    def get_warning_limit(self) -> Decimal:
        """Get warning threshold amount."""
        return self.limit_quote * Decimal(str(self.warning_threshold))


# ============== Result Classes ==============

@dataclass
class DailyLossMetrics:
    """Daily loss calculation metrics."""

    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    fees_paid: Decimal
    trades_count: int
    worst_trade: Optional[Decimal]
    best_trade: Optional[Decimal]
    calculation_time: datetime
    period_start: datetime
    period_end: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "realized_pnl": float(self.realized_pnl),
            "unrealized_pnl": float(self.unrealized_pnl),
            "total_pnl": float(self.total_pnl),
            "fees_paid": float(self.fees_paid),
            "trades_count": self.trades_count,
            "worst_trade": float(self.worst_trade) if self.worst_trade is not None else None,
            "best_trade": float(self.best_trade) if self.best_trade is not None else None,
            "calculation_time": self.calculation_time.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }


@dataclass
class RuleCheckResult:
    """Result of risk rule check."""

    action: RuleAction
    severity: RuleSeverity
    reason: str
    metrics: DailyLossMetrics
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

class DailyLossRule:
    """
    Daily loss limit risk rule.

    Monitors daily realized PnL and blocks trading when losses
    exceed configured threshold. Supports warning thresholds and
    custom reset times.

    Features:
    - Configurable daily loss limit in quote currency
    - Warning threshold before limit
    - Optional inclusion of fees and unrealized PnL
    - Custom reset time (not just midnight)
    - Allow closing positions even after limit
    """

    def __init__(self, config: DailyLossConfig):
        """
        Initialize daily loss rule.

        Args:
            config: Rule configuration
        """
        # Normalize warning_threshold into [0.0, 1.0]
        wt = max(0.0, min(1.0, float(config.warning_threshold)))
        if wt != config.warning_threshold:
            _log.warning("daily_loss_warning_threshold_clamped", extra={"given": config.warning_threshold, "used": wt})
            object.__setattr__(config, "warning_threshold", wt)  # dataclass(frozen=True) trick

        self.config = config
        self._last_reset_time: Optional[datetime] = None
        self._cached_metrics: Optional[DailyLossMetrics] = None

    async def check(
        self,
        symbol: str,
        trades_repo: Any,
        position: Optional[Any] = None,
        current_price: Optional[Decimal] = None,
        is_closing: bool = False,
    ) -> RuleCheckResult:
        """
        Check if daily loss limit is exceeded.

        Args:
            symbol: Trading symbol
            trades_repo: Trades repository
            position: Current position (for unrealized PnL)
            current_price: Current market price
            is_closing: Whether this is a closing trade

        Returns:
            Rule check result with action and metrics
        """
        # Rule disabled
        if not self.config.is_enabled():
            return self._create_disabled_result()

        # Allow closes even after limit, if configured
        if is_closing and self.config.allow_closes_after_limit:
            return self._create_allowed_close_result()

        # Calculate daily PnL
        metrics = await self._calculate_daily_metrics(
            symbol=symbol,
            trades_repo=trades_repo,
            position=position,
            current_price=current_price,
        )

        # Choose realized or total PnL for comparison
        pnl_to_check = metrics.total_pnl if self.config.include_unrealized else metrics.realized_pnl

        # Thresholds
        limit = self.config.limit_quote
        warning_limit = self.config.get_warning_limit()

        # Loss is negative: check <= -limit
        if pnl_to_check <= -limit:
            return self._create_result(
                action=RuleAction.BLOCK,
                severity=RuleSeverity.CRITICAL,
                reason=f"Daily loss limit exceeded: {pnl_to_check:.2f} <= -{limit:.2f}",
                metrics=metrics,
            )

        if pnl_to_check <= -warning_limit:
            pct_of_limit = abs(float((pnl_to_check / limit) * 100)) if limit > 0 else 0.0
            return self._create_result(
                action=RuleAction.WARN,
                severity=RuleSeverity.WARNING,
                reason=f"Approaching daily loss limit: {pnl_to_check:.2f} ({pct_of_limit:.1f}% of limit)",
                metrics=metrics,
            )

        # Safe
        return self._create_result(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Within daily loss limits",
            metrics=metrics,
        )

    async def _calculate_daily_metrics(
        self,
        symbol: str,
        trades_repo: Any,
        position: Optional[Any] = None,
        current_price: Optional[Decimal] = None,
    ) -> DailyLossMetrics:
        """Calculate daily PnL metrics."""
        # Determine period [start, end]
        period_start, period_end = self._get_period_boundaries()

        # Cache valid within the current period_start
        if self._cached_metrics and self._cached_metrics.period_start == period_start:
            # Refresh only unrealized if requested
            if self.config.include_unrealized and position is not None and current_price:
                self._cached_metrics.unrealized_pnl = self._calculate_unrealized_pnl(position, current_price)
                self._cached_metrics.total_pnl = self._cached_metrics.realized_pnl + self._cached_metrics.unrealized_pnl
            return self._cached_metrics

        # Load trades for the current period
        trades = await self._get_period_trades(
            symbol=symbol,
            trades_repo=trades_repo,
            start=period_start,
            end=period_end,
        )

        # Realized PnL/fees accumulation
        realized_pnl = dec("0")
        fees_paid = dec("0")
        worst_trade: Optional[Decimal] = None
        best_trade: Optional[Decimal] = None

        # Best-effort chronological ordering
        def _ts(t: dict[str, Any]) -> Any:
            return t.get("timestamp") or t.get("time") or t.get("ts")

        try:
            trades = sorted(trades, key=_ts)  # safe even if some keys missing
        except Exception:
            pass

        for trade in trades:
            trade_pnl = self._extract_trade_pnl(trade)
            if trade_pnl is not None:
                realized_pnl += trade_pnl
                worst_trade = trade_pnl if worst_trade is None else min(worst_trade, trade_pnl)
                best_trade = trade_pnl if best_trade is None else max(best_trade, trade_pnl)

            if self.config.include_fees:
                fees_paid += self._extract_trade_fee(trade)

        if self.config.include_fees:
            realized_pnl -= fees_paid  # fees reduce realized PnL

        unrealized_pnl = dec("0")
        if self.config.include_unrealized and position is not None and current_price:
            unrealized_pnl = self._calculate_unrealized_pnl(position, current_price)

        metrics = DailyLossMetrics(
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=realized_pnl + unrealized_pnl,
            fees_paid=fees_paid,
            trades_count=len(trades),
            worst_trade=worst_trade,
            best_trade=best_trade,
            calculation_time=datetime.now(timezone.utc),
            period_start=period_start,
            period_end=period_end,
        )

        self._cached_metrics = metrics
        return metrics

    def _normalize_reset_hour(self, hour: Optional[int]) -> Optional[int]:
        """Clamp reset hour to [0, 23] if provided."""
        if hour is None:
            return None
        try:
            h = int(hour)
        except Exception:
            return None
        return max(0, min(23, h))

    def _get_period_boundaries(self) -> tuple[datetime, datetime]:
        """Get current period start and inclusive end in UTC."""
        now = datetime.now(timezone.utc)
        reset_hour = self._normalize_reset_hour(self.config.reset_hour_utc)

        if reset_hour is not None:
            today_reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
            period_start = today_reset if now >= today_reset else (today_reset - timedelta(days=1))
        else:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        period_end = now  # inclusive "now"
        return period_start, period_end

    async def _get_period_trades(
        self,
        symbol: str,
        trades_repo: Any,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Get trades for the specified period (tolerant to repo shape)."""
        # 1) get_by_date_range with date objects
        if hasattr(trades_repo, "get_by_date_range"):
            try:
                return await _maybe_await(
                    trades_repo.get_by_date_range,
                    symbol=symbol,
                    start_date=start.date(),
                    end_date=end.date(),
                )
            except Exception:
                # 2) try datetime boundaries
                try:
                    return await _maybe_await(
                        trades_repo.get_by_date_range,
                        symbol=symbol,
                        start_date=start,
                        end_date=end,
                    )
                except Exception:
                    pass

        # 3) same-day -> list_today
        if start.date() == end.date() and hasattr(trades_repo, "list_today"):
            try:
                return await _maybe_await(trades_repo.list_today, symbol)
            except Exception:
                pass

        # 4) get_since
        if hasattr(trades_repo, "get_since"):
            try:
                return await _maybe_await(trades_repo.get_since, symbol, start)
            except Exception:
                pass

        _log.debug("daily_loss_trades_repo_fallback", extra={"symbol": symbol})
        return []

    def _extract_trade_pnl(self, trade: dict[str, Any]) -> Optional[Decimal]:
        """Extract PnL from trade record."""
        for field in ("pnl", "realized_pnl", "pnl_quote"):
            if field in trade and trade[field] is not None:
                return dec(str(trade[field]))

        # Optional: profit field for sells
        side = str(trade.get("side", "")).lower()
        if side == "sell" and "profit" in trade and trade["profit"] is not None:
            return dec(str(trade["profit"]))

        return None

    def _extract_trade_fee(self, trade: dict[str, Any]) -> Decimal:
        """Extract fee from trade record."""
        for field in ("fee_quote", "fee", "commission"):
            if field in trade and trade[field] is not None:
                try:
                    return abs(dec(str(trade[field])))
                except Exception:
                    return dec("0")
        return dec("0")

    def _calculate_unrealized_pnl(self, position: Any, current_price: Decimal) -> Decimal:
        """Calculate unrealized PnL for current position."""
        amount = dec(str(_get(position, "amount", "0")))
        entry_price = dec(str(_get(position, "entry_price", "0")))

        if amount == 0 or entry_price <= 0 or current_price <= 0:
            return dec("0")

        # long if amount>0, short if amount<0
        return (current_price - entry_price) * amount

    def _create_result(
        self,
        action: RuleAction,
        severity: RuleSeverity,
        reason: str,
        metrics: DailyLossMetrics,
    ) -> RuleCheckResult:
        """Create rule check result and log."""
        details = {
            "limit_quote": float(self.config.limit_quote),
            "warning_limit": float(self.config.get_warning_limit()),
            "include_fees": self.config.include_fees,
            "include_unrealized": self.config.include_unrealized,
            "allow_closes_after_limit": self.config.allow_closes_after_limit,
            "reset_hour_utc": self._normalize_reset_hour(self.config.reset_hour_utc),
        }

        log_extra = {
            "action": action.value,
            "pnl": float(metrics.total_pnl),
            "limit": float(self.config.limit_quote),
        }

        if severity == RuleSeverity.CRITICAL:
            _log.error("daily_loss_limit_exceeded", extra=log_extra)
        elif severity == RuleSeverity.WARNING:
            _log.warning("daily_loss_warning", extra=log_extra)
        else:
            _log.debug("daily_loss_check", extra=log_extra)

        return RuleCheckResult(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            details=details,
        )

    def _create_disabled_result(self) -> RuleCheckResult:
        """Create result for disabled rule."""
        now = datetime.now(timezone.utc)
        metrics = DailyLossMetrics(
            realized_pnl=dec("0"),
            unrealized_pnl=dec("0"),
            total_pnl=dec("0"),
            fees_paid=dec("0"),
            trades_count=0,
            worst_trade=None,
            best_trade=None,
            calculation_time=now,
            period_start=now,
            period_end=now,
        )

        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Rule disabled",
            metrics=metrics,
            details={"limit_quote": 0},
        )

    def _create_allowed_close_result(self) -> RuleCheckResult:
        """Create result for allowed closing trade."""
        now = datetime.now(timezone.utc)
        metrics = self._cached_metrics or DailyLossMetrics(
            realized_pnl=dec("0"),
            unrealized_pnl=dec("0"),
            total_pnl=dec("0"),
            fees_paid=dec("0"),
            trades_count=0,
            worst_trade=None,
            best_trade=None,
            calculation_time=now,
            period_start=now,
            period_end=now,
        )

        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Closing trades allowed",
            metrics=metrics,
            details={"is_closing": True},
        )

    def reset_cache(self) -> None:
        """Reset cached metrics (for manual reset or testing)."""
        self._cached_metrics = None
        self._last_reset_time = datetime.now(timezone.utc)
        _log.info("daily_loss_cache_reset")


# ============== Helper Functions ==============

def create_daily_loss_rule(settings: Any) -> DailyLossRule:
    """
    Factory function to create daily loss rule from settings.

    Args:
        settings: Application settings

    Returns:
        Configured DailyLossRule
    """
    config = DailyLossConfig(
        limit_quote=dec(str(getattr(settings, "RISK_DAILY_LOSS_LIMIT_QUOTE", 0))),
        warning_threshold=float(getattr(settings, "RISK_DAILY_LOSS_WARNING_PCT", 0.8)),
        include_fees=bool(getattr(settings, "RISK_DAILY_LOSS_INCLUDE_FEES", True)),
        include_unrealized=bool(getattr(settings, "RISK_DAILY_LOSS_INCLUDE_UNREALIZED", False)),
        reset_hour_utc=getattr(settings, "RISK_DAILY_LOSS_RESET_HOUR", None),
        allow_closes_after_limit=bool(getattr(settings, "RISK_DAILY_LOSS_ALLOW_CLOSES", True)),
    )

    return DailyLossRule(config)
