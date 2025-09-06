"""Correlation and anti-correlation risk rule.

Located in domain/risk/rules layer - manages position correlations.
Prevents holding correlated positions that amplify risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Callable, Awaitable, Iterable, Dict, Tuple

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


class CorrelationType(Enum):
    """Types of correlation relationships."""

    POSITIVE = "positive"        # Positively correlated (move together)
    NEGATIVE = "negative"        # Negatively correlated (move opposite / hedge)
    NEUTRAL = "neutral"          # No significant correlation
    ANTI = "anti"                # Should not hold together (mutually exclusive)


class CorrelationStrength(Enum):
    """Strength of correlation."""

    WEAK = "weak"         # 0.3 - 0.5 correlation
    MODERATE = "moderate" # 0.5 - 0.7 correlation
    STRONG = "strong"     # 0.7 - 0.9 correlation
    PERFECT = "perfect"   # > 0.9 correlation


# ============== Configuration ==============

@dataclass(frozen=True)
class CorrelationGroup:
    """Group of correlated symbols."""

    symbols: list[str]
    correlation_type: CorrelationType
    strength: CorrelationStrength
    max_positions: int = 1  # Max simultaneously open positions allowed in this group
    reduce_size_pct: float = 0.5  # Multiply size by this factor if multiple positions allowed
    description: Optional[str] = None

    def contains(self, symbol: str) -> bool:
        """Check if symbol is in this group."""
        s = symbol.upper()
        return any(s == x.upper() for x in self.symbols)

    def normalized_symbols(self) -> list[str]:
        return [s.upper() for s in self.symbols]


@dataclass(frozen=True)
class CorrelationConfig:
    """Configuration for correlation rule."""

    # Groups of correlated/anti-correlated symbols
    groups: list[CorrelationGroup]

    # Whether to block or just warn on violations
    block_on_violation: bool = True

    # Allow closing positions even if correlated
    allow_closes: bool = True

    # Maximum total exposure across correlated group (percentage of account balance)
    max_correlated_exposure_pct: float = 100.0  # % of account

    # Whether to consider position sizes when enforcing exposure limits
    consider_position_size: bool = True

    # Historical correlation lookback (days) — reserved for future use
    correlation_period_days: int = 30

    def is_enabled(self) -> bool:
        """Check if rule is enabled."""
        return len(self.groups) > 0

    def find_group(self, symbol: str) -> Optional[CorrelationGroup]:
        """Find correlation group for symbol."""
        for group in self.groups:
            if group.contains(symbol):
                return group
        return None


# ============== Result Classes ==============

@dataclass
class CorrelationMetrics:
    """Correlation analysis metrics."""

    symbol: str
    group: Optional[CorrelationGroup]
    open_positions: list[str]
    correlated_positions: list[str]
    total_exposure: Decimal
    max_allowed_exposure: Decimal
    exposure_pct: Optional[float]
    correlation_coefficient: Optional[float]
    calculation_time: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "group": self.group.normalized_symbols() if self.group else None,
            "open_positions": self.open_positions,
            "correlated_positions": self.correlated_positions,
            "total_exposure": float(self.total_exposure),
            "max_allowed_exposure": float(self.max_allowed_exposure),
            "exposure_pct": self.exposure_pct,
            "correlation_coefficient": self.correlation_coefficient,
            "calculation_time": self.calculation_time.isoformat(),
        }


@dataclass
class RuleCheckResult:
    """Result of risk rule check."""

    action: RuleAction
    severity: RuleSeverity
    reason: str
    metrics: CorrelationMetrics
    details: dict[str, Any]

    @property
    def is_blocked(self) -> bool:
        return self.action == RuleAction.BLOCK

    @property
    def is_warning(self) -> bool:
        return self.action == RuleAction.WARN

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "severity": self.severity.value,
            "reason": self.reason,
            "metrics": self.metrics.to_dict(),
            "details": self.details,
        }


# ============== Helpers ==============

async def _maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call function that might be sync or async."""
    try:
        res = fn(*args, **kwargs)
    except TypeError:
        # re-raise programming errors
        raise
    if hasattr(res, "__await__"):
        return await res  # type: ignore[func-returns-value]
    return res


def _norm_symbol(s: str) -> str:
    return s.upper()


def _dec_get(obj: Any, *keys: str, default: Decimal = Decimal("0")) -> Decimal:
    """Try to extract numeric via several keys/attrs and coerce to Decimal."""
    for k in keys:
        if isinstance(obj, dict) and k in obj and obj[k] is not None:
            try:
                return dec(str(obj[k]))
            except Exception:
                continue
        if hasattr(obj, k):
            try:
                v = getattr(obj, k)
                if v is not None:
                    return dec(str(v))
            except Exception:
                continue
    return default


# ============== Main Rule ==============

class CorrelationManager:
    """
    Correlation and anti-correlation risk manager.

    Manages position correlations to prevent excessive risk concentration.
    Blocks or warns when attempting to open positions in correlated assets.

    Features:
    - Correlation groups with different types and strengths
    - Maximum positions per group (ANTI → mutually exclusive)
    - Position-size-based exposure limits
    - Allow closing trades when configured
    """

    def __init__(self, config: CorrelationConfig):
        self.config = config
        self._correlation_cache: dict[tuple[str, str], float] = {}
        self._cache_expiry = 3600  # seconds; reserved for future coefficient calc
        self._last_cache_update: Optional[datetime] = None

    async def check(
        self,
        symbol: str,
        positions_repo: Any,
        is_closing: bool = False,
        position_size: Optional[Decimal] = None,
        account_balance: Optional[Decimal] = None,
    ) -> RuleCheckResult:
        """Check correlation constraints for a potential trade."""
        # Disabled
        if not self.config.is_enabled():
            return self._create_disabled_result(symbol)

        # Allow closes if configured
        if is_closing and self.config.allow_closes:
            return self._create_allowed_close_result(symbol)

        # Open positions (symbol → {"size": Decimal, "value": Decimal})
        open_positions = await self._get_open_positions(positions_repo)
        norm_symbol = _norm_symbol(symbol)

        # Group for the target symbol
        group = self.config.find_group(norm_symbol)

        # Calculate metrics
        metrics = await self._calculate_metrics(
            symbol=norm_symbol,
            group=group,
            open_positions=open_positions,
            position_size=position_size,
            account_balance=account_balance,
        )

        # Enforce ANTI groups (mutual exclusion): forbid any simultaneous holdings
        if group and group.correlation_type == CorrelationType.ANTI:
            if metrics.correlated_positions:
                return self._violation_result(
                    reason="Mutually exclusive group (ANTI) already has an open position",
                    metrics=metrics,
                    group=group,
                )

        # For other groups, enforce max positions
        if group and metrics.correlated_positions:
            # Determine effective max positions for this group
            max_positions = group.max_positions
            # Safety: if someone configured 0 for non-ANTI, treat as 1
            if max_positions < 0:
                max_positions = 0
            if group.correlation_type != CorrelationType.ANTI and max_positions == 0:
                max_positions = 1

            # Count open positions in group (excluding the prospective one)
            already_open = len(metrics.correlated_positions)

            if already_open >= max_positions:
                return self._violation_result(
                    reason=f"Maximum {max_positions} open position(s) already in correlated group",
                    metrics=metrics,
                    group=group,
                )

            # Suggest size reduction if allowed by policy
            if group.reduce_size_pct < 1.0:
                return self._create_result(
                    action=RuleAction.REDUCE_SIZE,
                    severity=RuleSeverity.WARNING,
                    reason=f"Reduce size by {(1 - group.reduce_size_pct) * 100:.0f}% due to correlation",
                    metrics=metrics,
                    group=group,
                )

        # Exposure limits across correlated positions (if balance provided)
        if self.config.consider_position_size and account_balance:
            if account_balance > 0:
                exposure_pct = float(metrics.total_exposure / account_balance * 100)
                if exposure_pct > self.config.max_correlated_exposure_pct:
                    return self._create_result(
                        action=RuleAction.BLOCK,
                        severity=RuleSeverity.CRITICAL,
                        reason=f"Total correlated exposure {exposure_pct:.1f}% exceeds limit",
                        metrics=metrics,
                        group=group,
                    )

        # All checks passed
        return self._create_result(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="No correlation violations",
            metrics=metrics,
            group=group,
        )

    # ---------- internals ----------

    async def _get_open_positions(self, positions_repo: Any) -> Dict[str, Dict[str, Decimal]]:
        """Get open positions from repository (sync/async tolerant)."""
        items = None

        # Try common methods
        for meth in ("list_open", "list", "get_all_positions"):
            if hasattr(positions_repo, meth):
                try:
                    items = await _maybe_await(getattr(positions_repo, meth))
                    if items:
                        break
                except Exception:
                    continue

        positions: Dict[str, Dict[str, Decimal]] = {}
        if not items:
            return positions

        # Accept any iterable
        if isinstance(items, Iterable):
            for it in items:
                sym = None
                # symbol
                if isinstance(it, dict):
                    sym = it.get("symbol") or it.get("pair") or it.get("asset")
                    size = _dec_get(it, "size", "amount", "qty", "base_qty", default=Decimal("0"))
                    value = _dec_get(it, "value", default=size)
                else:
                    sym = getattr(it, "symbol", None) or getattr(it, "pair", None) or getattr(it, "asset", None)
                    size = _dec_get(it, "size", "amount", "qty", "base_qty", default=Decimal("0"))
                    value = _dec_get(it, "value", default=size)

                if sym:
                    ns = _norm_symbol(str(sym))
                    if size > 0:
                        positions[ns] = {"size": size, "value": value}

        return positions

    async def _calculate_metrics(
        self,
        symbol: str,
        group: Optional[CorrelationGroup],
        open_positions: Dict[str, Dict[str, Decimal]],
        position_size: Optional[Decimal],
        account_balance: Optional[Decimal],
    ) -> CorrelationMetrics:
        correlated_positions: list[str] = []
        total_exposure = dec("0")

        # Find currently open positions inside the same group
        if group:
            gset = set(group.normalized_symbols())
            for pos_sym, payload in open_positions.items():
                if pos_sym != symbol and pos_sym in gset:
                    correlated_positions.append(pos_sym)
                    total_exposure += payload.get("value", dec("0"))

        # Add candidate position size to exposure
        if position_size:
            total_exposure += position_size

        # Max exposure in quote units (if balance known) else as fraction of 1.0
        if account_balance and account_balance > 0:
            max_allowed_exposure = account_balance * dec(str(self.config.max_correlated_exposure_pct / 100.0))
            exposure_pct: Optional[float] = float(total_exposure / account_balance * 100)
        else:
            # If balance isn't provided, express limit in relative terms and keep pct None
            max_allowed_exposure = dec(str(self.config.max_correlated_exposure_pct / 100.0))
            exposure_pct = None

        return CorrelationMetrics(
            symbol=symbol,
            group=group,
            open_positions=sorted(list(open_positions.keys())),
            correlated_positions=sorted(correlated_positions),
            total_exposure=total_exposure,
            max_allowed_exposure=max_allowed_exposure,
            exposure_pct=exposure_pct,
            correlation_coefficient=None,  # reserved; can be computed from history source
            calculation_time=datetime.now(timezone.utc),
        )

    # ---------- result builders & logging ----------

    def _violation_result(self, reason: str, metrics: CorrelationMetrics, group: CorrelationGroup) -> RuleCheckResult:
        """Helper that decides between BLOCK/WARN per policy."""
        action = RuleAction.BLOCK if self.config.block_on_violation else RuleAction.WARN
        severity = RuleSeverity.CRITICAL if action == RuleAction.BLOCK else RuleSeverity.WARNING
        return self._create_result(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            group=group,
        )

    def _create_result(
        self,
        action: RuleAction,
        severity: RuleSeverity,
        reason: str,
        metrics: CorrelationMetrics,
        group: Optional[CorrelationGroup] = None,
    ) -> RuleCheckResult:
        details: dict[str, Any] = {
            "block_on_violation": self.config.block_on_violation,
            "allow_closes": self.config.allow_closes,
            "max_correlated_exposure_pct": self.config.max_correlated_exposure_pct,
            "consider_position_size": self.config.consider_position_size,
        }

        if group:
            details.update(
                {
                    "group_symbols": group.normalized_symbols(),
                    "correlation_type": group.correlation_type.value,
                    "strength": group.strength.value,
                    "max_positions": group.max_positions,
                    "reduce_size_pct": group.reduce_size_pct,
                }
            )

        log_extra = {
            "symbol": metrics.symbol,
            "action": action.value,
            "correlated_positions": metrics.correlated_positions,
            "exposure_pct": metrics.exposure_pct,
        }

        if action == RuleAction.BLOCK:
            _log.warning("correlation_violation_blocked", extra=log_extra)
        elif action == RuleAction.WARN:
            _log.info("correlation_warning", extra=log_extra)
        else:
            _log.debug("correlation_check", extra=log_extra)

        return RuleCheckResult(
            action=action,
            severity=severity,
            reason=reason,
            metrics=metrics,
            details=details,
        )

    def _create_disabled_result(self, symbol: str) -> RuleCheckResult:
        metrics = CorrelationMetrics(
            symbol=_norm_symbol(symbol),
            group=None,
            open_positions=[],
            correlated_positions=[],
            total_exposure=dec("0"),
            max_allowed_exposure=dec("0"),
            exposure_pct=None,
            correlation_coefficient=None,
            calculation_time=datetime.now(timezone.utc),
        )
        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Rule disabled",
            metrics=metrics,
            details={"groups": 0},
        )

    def _create_allowed_close_result(self, symbol: str) -> RuleCheckResult:
        metrics = CorrelationMetrics(
            symbol=_norm_symbol(symbol),
            group=None,
            open_positions=[],
            correlated_positions=[],
            total_exposure=dec("0"),
            max_allowed_exposure=dec("0"),
            exposure_pct=None,
            correlation_coefficient=None,
            calculation_time=datetime.now(timezone.utc),
        )
        return RuleCheckResult(
            action=RuleAction.ALLOW,
            severity=RuleSeverity.INFO,
            reason="Closing trades allowed",
            metrics=metrics,
            details={"is_closing": True},
        )


# ============== Factory Function ==============

def create_correlation_manager(settings: Any) -> CorrelationManager:
    """
    Factory function to create correlation manager from settings.

    Settings example:
      RISK_CORRELATION_GROUPS = [
        {"symbols": ["BTC/USDT","ETH/USDT"], "type": "positive", "strength": "strong", "max_positions": 1},
        {"symbols": ["XRP/USDT","ADA/USDT"], "type": "anti", "strength": "perfect"}
      ]
    """
    raw_groups = getattr(settings, "RISK_CORRELATION_GROUPS", [])
    groups: list[CorrelationGroup] = []

    for raw in raw_groups:
        try:
            if isinstance(raw, dict):
                symbols = [str(s) for s in raw.get("symbols", [])]
                type_str = str(raw.get("type", "positive")).lower()
                strength_str = str(raw.get("strength", "moderate")).lower()

                # parse enums defensively
                try:
                    corr_type = CorrelationType(type_str)
                except Exception:
                    corr_type = CorrelationType.POSITIVE
                try:
                    strength = CorrelationStrength(strength_str)
                except Exception:
                    strength = CorrelationStrength.MODERATE

                max_positions = int(raw.get("max_positions", 1))
                reduce_size_pct = float(raw.get("reduce_size_pct", 0.5))
                reduce_size_pct = max(0.0, min(1.0, reduce_size_pct))
                description = raw.get("description")

                # ANTI groups default to mutual exclusion if not explicitly set
                if corr_type == CorrelationType.ANTI and "max_positions" not in raw:
                    max_positions = 0  # strict mutual exclusion

                groups.append(
                    CorrelationGroup(
                        symbols=symbols,
                        correlation_type=corr_type,
                        strength=strength,
                        max_positions=max_positions,
                        reduce_size_pct=reduce_size_pct,
                        description=description,
                    )
                )

            elif isinstance(raw, list):
                # Legacy format: just list of symbols → treat as ANTI mutual exclusion
                symbols = [str(s) for s in raw]
                groups.append(
                    CorrelationGroup(
                        symbols=symbols,
                        correlation_type=CorrelationType.ANTI,
                        strength=CorrelationStrength.STRONG,
                        max_positions=0,  # mutual exclusion
                        reduce_size_pct=0.5,
                    )
                )
        except Exception as e:
            _log.warning("correlation_group_parse_failed", extra={"error": str(e), "raw": repr(raw)})

    config = CorrelationConfig(
        groups=groups,
        block_on_violation=bool(getattr(settings, "RISK_CORRELATION_BLOCK", True)),
        allow_closes=bool(getattr(settings, "RISK_CORRELATION_ALLOW_CLOSES", True)),
        max_correlated_exposure_pct=float(getattr(settings, "RISK_MAX_CORRELATED_EXPOSURE_PCT", 100.0)),
        consider_position_size=bool(getattr(settings, "RISK_CORRELATION_CONSIDER_SIZE", True)),
        correlation_period_days=int(getattr(settings, "RISK_CORRELATION_PERIOD_DAYS", 30)),
    )

    return CorrelationManager(config)
