"""Cooldown period risk rule.

Located in domain/risk/rules layer - enforces minimum time between trades.
Prevents overtrading and emotional decisions by requiring cooldown period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Callable, Awaitable, Iterable, Tuple, Dict

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


class CooldownType(Enum):
    """Types of cooldown periods."""

    AFTER_TRADE = "after_trade"      # After any trade
    AFTER_WIN = "after_win"          # After winning trade
    AFTER_LOSS = "after_loss"        # After losing trade
    AFTER_ERROR = "after_error"      # After trade error
    PROGRESSIVE = "progressive"      # Increases with consecutive trades


# ============== Configuration ==============

@dataclass(frozen=True)
class CooldownConfig:
    """Configuration for cooldown rule."""

    # Base cooldown in seconds (0 = disabled)
    cooldown_sec: int = 0

    # Type of cooldown
    cooldown_type: CooldownType = CooldownType.AFTER_TRADE

    # Different cooldowns for different outcomes
    cooldown_after_win_sec: Optional[int] = None
    cooldown_after_loss_sec: Optional[int] = None
    cooldown_after_error_sec: Optional[int] = None

    # Progressive cooldown settings
    progressive_factor: float = 1.5  # Multiply cooldown by this for each consecutive trade
    progressive_max_sec: int = 300   # Maximum cooldown in progressive mode
    progressive_reset_after_sec: int = 3600  # Reset progressive counter after this time

    # Allow closing positions during cooldown
    allow_closes_during_cooldown: bool = True

    # Minimum time between same symbol trades
    same_symbol_cooldown_sec: Optional[int] = None

    def is_enabled(self) -> bool:
        """Check if rule is enabled."""
        return int(self.cooldown_sec) > 0

    def get_cooldown_for_outcome(self, outcome: str) -> int:
        """Get cooldown duration based on trade outcome (falls back to base)."""
        if outcome == "win" and self.cooldown_after_win_sec is not None:
            return int(self.cooldown_after_win_sec)
        if outcome == "loss" and self.cooldown_after_loss_sec is not None:
            return int(self.cooldown_after_loss_sec)
        if outcome == "error" and self.cooldown_after_error_sec is not None:
            return int(self.cooldown_after_error_sec)
        return int(self.cooldown_sec)


# ============== Result Classes ==============

@dataclass
class CooldownMetrics:
    """Cooldown calculation metrics."""

    last_trade_time: Optional[datetime]
    time_since_last_trade_sec: Optional[float]
    required_cooldown_sec: int
    remaining_cooldown_sec: float
    consecutive_trades: int
    last_trade_outcome: Optional[str]
    is_closing_trade: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
            "time_since_last_trade_sec": self.time_since_last_trade_sec,
            "required_cooldown_sec": self.required_cooldown_sec,
            "remaining_cooldown_sec": self.remaining_cooldown_sec,
            "consecutive_trades": self.consecutive_trades,
            "last_trade_outcome": self.last_trade_outcome,
            "is_closing_trade": self.is_closing_trade,
        }


@dataclass
class RuleCheckResult:
    """Result of risk rule check."""

    action: RuleAction
    severity: RuleSeverity
    reason: str
    metrics: CooldownMetrics
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


# ============== Helpers ==============

async def _maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a function that may be sync or async."""
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


def _parse_trade_time(value: Any) -> Optional[datetime]:
    """Parse various timestamp representations to aware UTC datetime."""
    try:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            # assume ms if large
            ts = float(value) / 1000.0 if float(value) > 1e10 else float(value)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(value, str):
            # accept ISO strings; support trailing Z
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return None


# ============== Main Rule ==============

class CooldownRule:
    """
    Cooldown period risk rule.

    Enforces minimum time between trades to prevent overtrading
    and emotional decisions. Supports different cooldown periods
    based on trade outcomes and progressive cooldowns.

    Features:
    - Configurable cooldown periods
    - Different cooldowns for wins/losses/errors
    - Progressive cooldown (increases with consecutive trades)
    - Same-symbol cooldown
    - Allow closing positions during cooldown
    """

    def __init__(self, config: CooldownConfig):
        """
        Initialize cooldown rule.

        Args:
            config: Rule configuration
        """
        self.config = config
        self._consecutive_trades: Dict[str, int] = {}
        self._last_progressive_reset: Dict[str, datetime] = {}

    async def check(
        self,
        symbol: str,
        trades_repo: Any,
        is_closing: bool = False
    ) -> RuleCheckResult:
        """
        Check if cooldown period has passed.

        Args:
            symbol: Trading symbol
            trades_repo: Trades repository
            is_closing: Whether this is a closing trade

        Returns:
            Rule check result with action and metrics
        """
        # Disabled rule
        if not self.config.is_enabled():
            return self._create_disabled_result()

        # Allow closes if configured
        if is_closing and self.config.allow_closes_during_cooldown:
            return self._create_allowed_close_result()

        # Last trade (time + outcome)
        last_trade_info = await self._get_last_trade_info(symbol, trades_repo)

        if last_trade_info is None:
            # No previous trades — allow
            return self._create_result(
                action=RuleAction.ALLOW,
                severity=RuleSeverity.INFO,
                reason="No previous trades",
                metrics=self._create_metrics(None, 0.0, is_closing=is_closing),
            )

        last_trade_time, last_trade_outcome = last_trade_info
        now = datetime.now(timezone.utc)
        time_since_trade = max(0.0, (now - last_trade_time).total_seconds())

        # Required cooldown (base/outcome + progressive)
        required_cooldown = self._calculate_required_cooldown(
            symbol=symbol,
            outcome=last_trade_outcome,
            time_since_last=time_since_trade,
        )

        # Enforce same-symbol minimal interval (if configured)
        if self.config.same_symbol_cooldown_sec and self.config.same_symbol_cooldown_sec > 0:
            required_cooldown = max(required_cooldown, int(self.config.same_symbol_cooldown_sec))

        remaining_cooldown = max(0.0, float(required_cooldown) - time_since_trade)

        metrics = self._create_metrics(
            last_trade_time=last_trade_time,
            time_since_trade=time_since_trade,
            required_cooldown=required_cooldown,
            remaining_cooldown=remaining_cooldown,
            outcome=last_trade_outcome,
            is_closing=is_closing,
        )

        if remaining_cooldown > 0:
            # Still in cooldown — block (warning severity is enough)
            return self._create_result(
                action=RuleAction.BLOCK,
                severity=RuleSeverity.WARNING,
                reason=f"Cooldown period active: {remaining_cooldown:.1f}s remaining",
                metrics=metrics,
            )

        # Cooldown passed — allow
        return self._create_result(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Cooldown period passed",
            metrics=metrics,
        )

    # -------- repo access --------

    async def _get_last_trade_info(
        self,
        symbol: str,
        trades_repo: Any
    ) -> Optional[Tuple[datetime, str]]:
        """Get information about the last trade (tolerant to repo shape)."""
        # 1) get_last_trade(symbol)
        if hasattr(trades_repo, "get_last_trade"):
            try:
                trade = await _maybe_await(trades_repo.get_last_trade, symbol)
                if trade:
                    return self._extract_trade_info(trade)
            except Exception:
                pass

        # 2) last_trade_ts_ms(symbol) -> int ms
        if hasattr(trades_repo, "last_trade_ts_ms"):
            try:
                ts_ms = await _maybe_await(trades_repo.last_trade_ts_ms, symbol)
                if ts_ms:
                    dt = _parse_trade_time(ts_ms)
                    if dt:
                        return (dt, "unknown")
            except Exception:
                pass

        # 3) list_today(symbol) -> list
        if hasattr(trades_repo, "list_today"):
            try:
                trades = await _maybe_await(trades_repo.list_today, symbol)
                if trades:
                    latest: Optional[Any] = None
                    latest_time: Optional[datetime] = None

                    # Accept iterable
                    if isinstance(trades, Iterable):
                        for tr in trades:
                            t = self._extract_trade_time(tr)
                            if t and (latest_time is None or t > latest_time):
                                latest, latest_time = tr, t

                    if latest:
                        return self._extract_trade_info(latest)
            except Exception:
                pass

        return None

    def _extract_trade_time(self, trade: Any) -> Optional[datetime]:
        """Extract timestamp from trade record."""
        for field in ["timestamp", "ts", "time", "created_at", "executed_at"]:
            val = _get(trade, field, None)
            if val is not None:
                dt = _parse_trade_time(val)
                if dt:
                    return dt
        return None

    def _extract_trade_info(self, trade: Any) -> Tuple[datetime, str]:
        """Extract time and outcome from trade (win/loss/breakeven/error/unknown)."""
        trade_time = self._extract_trade_time(trade) or datetime.now(timezone.utc)

        outcome = "unknown"

        # Outcome by PnL
        pnl = None
        for field in ("pnl", "realized_pnl", "profit"):
            val = _get(trade, field, None)
            if val is not None:
                pnl = val
                break

        if pnl is not None:
            try:
                pv = float(pnl)
                outcome = "win" if pv > 0 else ("loss" if pv < 0 else "breakeven")
            except (TypeError, ValueError):
                pass

        # Outcome by status (errors)
        status = _get(trade, "status", None)
        if status and str(status).lower() in {"error", "failed", "rejected"}:
            outcome = "error"

        return trade_time, outcome

    # -------- cooldown math --------

    def _calculate_required_cooldown(
        self,
        symbol: str,
        outcome: str,
        time_since_last: float
    ) -> int:
        """Calculate required cooldown period (base/outcome + progressive if enabled)."""
        base = self.config.get_cooldown_for_outcome(outcome)

        if self.config.cooldown_type == CooldownType.PROGRESSIVE:
            now = datetime.now(timezone.utc)
            last_reset = self._last_progressive_reset.get(symbol)

            # reset progressive window if stale
            if last_reset is None or (now - last_reset).total_seconds() > int(self.config.progressive_reset_after_sec):
                self._consecutive_trades[symbol] = 0
                self._last_progressive_reset[symbol] = now

            # If трейдим "слишком рано" относительно базового окна — наращиваем счётчик
            if time_since_last < float(base):
                self._consecutive_trades[symbol] = self._consecutive_trades.get(symbol, 0) + 1

            consecutive = self._consecutive_trades.get(symbol, 0)
            if consecutive > 0:
                progressive = int(round(base * (float(self.config.progressive_factor) ** consecutive)))
                return min(progressive, int(self.config.progressive_max_sec))

        return int(base)

    # -------- results & logging --------

    def _create_metrics(
        self,
        last_trade_time: Optional[datetime],
        time_since_trade: float,
        required_cooldown: int = 0,
        remaining_cooldown: float = 0.0,
        outcome: Optional[str] = None,
        is_closing: bool = False
    ) -> CooldownMetrics:
        """Create cooldown metrics."""
        return CooldownMetrics(
            last_trade_time=last_trade_time,
            time_since_last_trade_sec=(time_since_trade if last_trade_time else None),
            required_cooldown_sec=int(required_cooldown),
            remaining_cooldown_sec=float(remaining_cooldown),
            consecutive_trades=sum(self._consecutive_trades.values()),
            last_trade_outcome=outcome,
            is_closing_trade=is_closing,
        )

    def _create_result(
        self,
        action: RuleAction,
        severity: RuleSeverity,
        reason: str,
        metrics: CooldownMetrics
    ) -> RuleCheckResult:
        """Create rule check result."""
        details = {
            "cooldown_type": self.config.cooldown_type.value,
            "base_cooldown_sec": int(self.config.cooldown_sec),
            "allow_closes": bool(self.config.allow_closes_during_cooldown),
            "same_symbol_cooldown_sec": int(self.config.same_symbol_cooldown_sec or 0),
        }

        log_extra = {
            "action": action.value,
            "remaining_sec": metrics.remaining_cooldown_sec,
            "required_sec": metrics.required_cooldown_sec,
        }

        if action == RuleAction.BLOCK:
            _log.info("cooldown_active", extra=log_extra)
        else:
            _log.debug("cooldown_check", extra=log_extra)

        return RuleCheckResult(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            details=details,
        )

    def _create_disabled_result(self) -> RuleCheckResult:
        """Create result for disabled rule."""
        metrics = self._create_metrics(None, 0.0, 0, 0.0)
        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Rule disabled",
            metrics=metrics,
            details={"cooldown_sec": 0},
        )

    def _create_allowed_close_result(self) -> RuleCheckResult:
        """Create result for allowed closing trade."""
        metrics = self._create_metrics(None, 0.0, 0, 0.0, is_closing=True)
        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Closing trades allowed during cooldown",
            metrics=metrics,
            details={"is_closing": True},
        )

    def reset_progressive_counter(self, symbol: str) -> None:
        """Reset progressive counter for symbol (manual reset)."""
        if symbol in self._consecutive_trades:
            del self._consecutive_trades[symbol]
        if symbol in self._last_progressive_reset:
            del self._last_progressive_reset[symbol]

        _log.info("progressive_counter_reset", extra={"symbol": symbol})


# ============== Factory Function ==============

def create_cooldown_rule(settings: Any) -> CooldownRule:
    """
    Factory function to create cooldown rule from settings.

    Args:
        settings: Application settings

    Returns:
        Configured CooldownRule
    """
    # Determine cooldown type
    cooldown_type_str = getattr(settings, "RISK_COOLDOWN_TYPE", "after_trade")
    try:
        cooldown_type = CooldownType(str(cooldown_type_str).lower())
    except Exception:
        cooldown_type = CooldownType.AFTER_TRADE

    config = CooldownConfig(
        cooldown_sec=int(getattr(settings, "RISK_COOLDOWN_SEC", 0)),
        cooldown_type=cooldown_type,
        cooldown_after_win_sec=getattr(settings, "RISK_COOLDOWN_AFTER_WIN_SEC", None),
        cooldown_after_loss_sec=getattr(settings, "RISK_COOLDOWN_AFTER_LOSS_SEC", None),
        cooldown_after_error_sec=getattr(settings, "RISK_COOLDOWN_AFTER_ERROR_SEC", None),
        progressive_factor=float(getattr(settings, "RISK_COOLDOWN_PROGRESSIVE_FACTOR", 1.5)),
        progressive_max_sec=int(getattr(settings, "RISK_COOLDOWN_PROGRESSIVE_MAX_SEC", 300)),
        progressive_reset_after_sec=int(getattr(settings, "RISK_COOLDOWN_PROGRESSIVE_RESET_SEC", 3600)),
        allow_closes_during_cooldown=bool(getattr(settings, "RISK_COOLDOWN_ALLOW_CLOSES", True)),
        same_symbol_cooldown_sec=getattr(settings, "RISK_COOLDOWN_SAME_SYMBOL_SEC", None),
    )

    return CooldownRule(config)
