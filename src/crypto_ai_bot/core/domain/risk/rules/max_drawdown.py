"""Max drawdown risk rule.

Located in domain/risk/rules layer - monitors and limits intraday drawdown.
Calculates equity curve from realized PnL using FIFO with fees.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Awaitable, Callable, Iterable

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.pnl import FIFOCalculator  # use the shared calculator

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
class MaxDrawdownConfig:
    """Configuration for max drawdown rule."""

    # Maximum allowed drawdown percentage (0 = disabled)
    max_drawdown_pct: float

    # Warning threshold (percentage before max)
    warning_threshold_pct: float = 0.8  # Warn at 80% of max

    # Whether to include unrealized PnL
    include_unrealized: bool = False

    # Lookback period (hours, 0 = today only)
    lookback_hours: int = 0

    # Whether to reset at midnight
    reset_daily: bool = True

    def is_enabled(self) -> bool:
        """Check if rule is enabled."""
        return self.max_drawdown_pct > 0

    def get_warning_level(self) -> float:
        """Get warning threshold percentage."""
        return self.max_drawdown_pct * self.warning_threshold_pct


# ============== Result Classes ==============

@dataclass
class DrawdownMetrics:
    """Drawdown calculation metrics."""

    current_equity: Decimal
    peak_equity: Decimal
    drawdown_amount: Decimal
    drawdown_pct: float
    trades_count: int
    calculation_time: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "current_equity": float(self.current_equity),
            "peak_equity": float(self.peak_equity),
            "drawdown_amount": float(self.drawdown_amount),
            "drawdown_pct": self.drawdown_pct,
            "trades_count": self.trades_count,
            "calculation_time": self.calculation_time.isoformat(),
        }


@dataclass
class RuleCheckResult:
    """Result of risk rule check."""

    action: RuleAction
    severity: RuleSeverity
    reason: str
    metrics: DrawdownMetrics
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

class MaxDrawdownRule:
    """
    Maximum drawdown risk rule.

    Monitors intraday equity curve and blocks trading when drawdown
    from peak exceeds configured threshold.

    Features:
    - FIFO-based PnL calculation with fees
    - Warning threshold before max
    - Configurable lookback period
    - Optional unrealized PnL inclusion
    """

    def __init__(self, config: MaxDrawdownConfig):
        """
        Initialize max drawdown rule.

        Args:
            config: Rule configuration
        """
        self.config = config
        self._peak_equity_cache: dict[str, Decimal] = {}
        self._last_calculation: Optional[datetime] = None

    async def check(
        self,
        symbol: str,
        trades_repo: Any,
        position: Optional[Any] = None,
        current_price: Optional[Decimal] = None
    ) -> RuleCheckResult:
        """
        Check if max drawdown limit is exceeded.

        Args:
            symbol: Trading symbol
            trades_repo: Trades repository
            position: Current position (for unrealized PnL)
            current_price: Current market price

        Returns:
            Rule check result with action and metrics
        """
        # Check if rule is enabled
        if not self.config.is_enabled():
            return self._create_result(
                action=RuleAction.ALLOW,
                severity=RuleSeverity.INFO,
                reason="Rule disabled",
                current_equity=dec("0"),
                peak_equity=dec("0"),
                drawdown_pct=0.0,
                trades_count=0,
            )

        # Calculate equity curve and drawdown
        metrics = await self._calculate_drawdown(
            symbol=symbol,
            trades_repo=trades_repo,
            position=position,
            current_price=current_price,
        )

        # Check thresholds
        max_dd = float(self.config.max_drawdown_pct)
        warning_dd = float(self.config.get_warning_level())
        current_dd = float(metrics.drawdown_pct)

        # Determine action
        if current_dd >= max_dd:
            # Max drawdown exceeded - block trading
            return self._create_result(
                action=RuleAction.BLOCK,
                severity=RuleSeverity.CRITICAL,
                reason=f"Max drawdown exceeded: {current_dd:.2f}% >= {max_dd:.2f}%",
                metrics=metrics,
            )

        if current_dd >= warning_dd:
            # Warning threshold reached
            return self._create_result(
                action=RuleAction.WARN,
                severity=RuleSeverity.WARNING,
                reason=f"Approaching max drawdown: {current_dd:.2f}% (limit: {max_dd:.2f}%)",
                metrics=metrics,
            )

        # Within safe limits
        return self._create_result(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Within drawdown limits",
            metrics=metrics,
        )

    async def _calculate_drawdown(
        self,
        symbol: str,
        trades_repo: Any,
        position: Optional[Any] = None,
        current_price: Optional[Decimal] = None
    ) -> DrawdownMetrics:
        """Calculate current drawdown metrics."""
        # Get trades based on lookback period
        trades = await self._get_trades(symbol, trades_repo)

        if not trades:
            # No trades - no drawdown
            return DrawdownMetrics(
                current_equity=dec("0"),
                peak_equity=dec("0"),
                drawdown_amount=dec("0"),
                drawdown_pct=0.0,
                trades_count=0,
                calculation_time=datetime.now(timezone.utc),
            )

        # Calculate equity curve using FIFO
        equity_curve = self._calculate_equity_curve(trades)

        # Add unrealized PnL if configured
        current_equity = equity_curve[-1] if equity_curve else dec("0")

        if self.config.include_unrealized and position is not None and current_price:
            unrealized_pnl = self._calculate_unrealized_pnl(position, current_price)
            current_equity += unrealized_pnl

        # Find peak equity
        peak_equity = max(equity_curve) if equity_curve else dec("0")

        # Update cached peak if daily reset is disabled
        if not self.config.reset_daily:
            cached_peak = self._peak_equity_cache.get(symbol, dec("0"))
            peak_equity = max(peak_equity, cached_peak)
            self._peak_equity_cache[symbol] = peak_equity

        # Calculate drawdown
        drawdown_amount = peak_equity - current_equity

        # Calculate percentage (avoid division by zero)
        drawdown_pct = 0.0
        if peak_equity > 0:
            try:
                drawdown_pct = float((drawdown_amount / peak_equity) * 100)
            except Exception:
                drawdown_pct = 0.0

        return DrawdownMetrics(
            current_equity=current_equity,
            peak_equity=peak_equity,
            drawdown_amount=drawdown_amount,
            drawdown_pct=max(0.0, drawdown_pct),  # Ensure non-negative
            trades_count=len(trades),
            calculation_time=datetime.now(timezone.utc),
        )

    def _calculate_equity_curve(self, trades: list[dict[str, Any]]) -> list[Decimal]:
        """
        Calculate equity curve from trades using FIFO.

        Returns list of cumulative PnL values (realized PnL only).
        """
        fifo = FIFOCalculator()
        equity_curve: list[Decimal] = []
        cumulative_pnl = dec("0")

        # Expect chronological order; if objects contain timestamps, we can sort best-effort
        def _ts(t: dict[str, Any]) -> Any:
            return t.get("timestamp") or t.get("time") or t.get("ts")

        try:
            trades = sorted(trades, key=_ts)  # safe even if keys missing
        except Exception:
            pass

        for trade in trades:
            side = str(trade.get("side", "")).lower()
            amount = dec(str(trade.get("amount", 0)))
            price = dec(str(trade.get("price", 0)))
            # fees can be provided as 'fee_quote' or 'fee'
            fee = dec(str(trade.get("fee_quote", trade.get("fee", 0))))

            if amount <= 0 or price <= 0:
                equity_curve.append(cumulative_pnl)
                continue

            if side == "buy":
                # Add to inventory (fee increases cost basis)
                fifo.add_buy(amount, price, fee)

            elif side == "sell":
                # Calculate realized PnL (fee decreases proceeds)
                realized_pnl = fifo.process_sell(amount, price, fee)
                cumulative_pnl += realized_pnl

            # Track equity over time (realized component)
            equity_curve.append(cumulative_pnl)

        return equity_curve

    def _calculate_unrealized_pnl(
        self,
        position: Any,
        current_price: Decimal
    ) -> Decimal:
        """Calculate unrealized PnL for current position."""
        if not position:
            return dec("0")

        amount = dec(str(_get(position, "amount", "0")))
        entry_price = dec(str(_get(position, "entry_price", "0")))

        if amount == 0 or entry_price <= 0 or current_price <= 0:
            return dec("0")

        # long if amount>0, short if amount<0 (sign respected)
        return (current_price - entry_price) * amount

    async def _get_trades(
        self,
        symbol: str,
        trades_repo: Any
    ) -> list[dict[str, Any]]:
        """Get trades respecting lookback period, tolerant to repo shape."""
        now = datetime.now(timezone.utc)

        # 1) lookback in hours
        if self.config.lookback_hours and self.config.lookback_hours > 0:
            since_dt = now - timedelta(hours=int(self.config.lookback_hours))

            # Prefer async method 'get_since(symbol, since)'
            if hasattr(trades_repo, "get_since"):
                return await _maybe_await(trades_repo.get_since, symbol, since_dt)

            # Fallback to 'get_by_date_range'
            if hasattr(trades_repo, "get_by_date_range"):
                # Try date-based first (common in your storages)
                try:
                    return await _maybe_await(
                        trades_repo.get_by_date_range,
                        symbol=symbol,
                        start_date=since_dt.date(),
                        end_date=now.date(),
                    )
                except Exception:
                    # Try datetime-based
                    return await _maybe_await(
                        trades_repo.get_by_date_range,
                        symbol=symbol,
                        start_date=since_dt,
                        end_date=now,
                    )

        # 2) today only (default)
        if hasattr(trades_repo, "list_today"):
            trades = await _maybe_await(trades_repo.list_today, symbol)
            # many repos return in reverse chrono; make ascending best-effort
            if isinstance(trades, Iterable):
                trades = list(trades)
                if len(trades) >= 2:
                    try:
                        if (_get(trades[0], "timestamp") or 0) > (_get(trades[-1], "timestamp") or 0):
                            trades.reverse()
                    except Exception:
                        pass
            return trades or []

        if hasattr(trades_repo, "get_by_date_range"):
            today = now.date()
            return await _maybe_await(
                trades_repo.get_by_date_range,
                symbol=symbol,
                start_date=today,
                end_date=today,
            )

        return []

    def _create_result(
        self,
        action: RuleAction,
        severity: RuleSeverity,
        reason: str,
        metrics: Optional[DrawdownMetrics] = None,
        **kwargs
    ) -> RuleCheckResult:
        """Create rule check result."""
        if not metrics:
            metrics = DrawdownMetrics(
                current_equity=kwargs.get("current_equity", dec("0")),
                peak_equity=kwargs.get("peak_equity", dec("0")),
                drawdown_amount=dec("0"),
                drawdown_pct=kwargs.get("drawdown_pct", 0.0),
                trades_count=kwargs.get("trades_count", 0),
                calculation_time=datetime.now(timezone.utc),
            )

        details = {
            "limit_pct": self.config.max_drawdown_pct,
            "warning_pct": self.config.get_warning_level(),
            "include_unrealized": self.config.include_unrealized,
            "lookback_hours": self.config.lookback_hours,
        }

        # Log based on severity
        log_extra = {
            "symbol": kwargs.get("symbol", ""),
            "action": action.value,
            "drawdown_pct": metrics.drawdown_pct,
            "limit_pct": self.config.max_drawdown_pct,
        }

        if severity == RuleSeverity.CRITICAL:
            _log.error("max_drawdown_exceeded", extra=log_extra)
        elif severity == RuleSeverity.WARNING:
            _log.warning("max_drawdown_warning", extra=log_extra)
        else:
            _log.debug("max_drawdown_check", extra=log_extra)

        return RuleCheckResult(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            details=details,
        )

    def reset_daily_peak(self, symbol: str) -> None:
        """Reset daily peak equity (for manual reset)."""
        if symbol in self._peak_equity_cache:
            del self._peak_equity_cache[symbol]

        _log.info("peak_equity_reset", extra={"symbol": symbol})
