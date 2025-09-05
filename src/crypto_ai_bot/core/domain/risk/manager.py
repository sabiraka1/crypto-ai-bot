"""
Risk Manager - Aggregates all risk rules and evaluates trading decisions.

This is pure domain logic - no external dependencies, no side effects.
All rules return structured results that application layer can use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# ============= RESULT TYPES =============

class RiskAction(Enum):
    """Action to take based on risk assessment"""
    ALLOW = "allow"           # Trade allowed
    BLOCK = "block"          # Trade blocked completely
    REDUCE = "reduce"        # Reduce position size
    WARN = "warn"           # Warning but allow


class RiskRuleType(Enum):
    """Types of risk rules"""
    # Critical rules (BLOCK)
    LOSS_STREAK = "loss_streak"
    MAX_DRAWDOWN = "max_drawdown"
    DAILY_LOSS = "daily_loss"
    BUDGET_ORDERS = "budget_orders"
    BUDGET_TURNOVER = "budget_turnover"
    
    # Soft rules (REDUCE/WARN)
    COOLDOWN = "cooldown"
    SPREAD_CAP = "spread_cap"
    CORRELATION = "correlation"
    
    # Monitoring rules (WARN only)
    ORDERS_5M = "orders_5m"
    TURNOVER_5M = "turnover_5m"


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of risk check"""
    allowed: bool
    action: RiskAction
    triggered_rule: Optional[RiskRuleType] = None
    reason: str = ""
    current_value: Optional[Decimal] = None
    threshold: Optional[Decimal] = None
    metadata: dict[str, any] = field(default_factory=dict)
    
    @classmethod
    def allow(cls) -> RiskCheckResult:
        """Create allow result"""
        return cls(allowed=True, action=RiskAction.ALLOW)
    
    @classmethod
    def block(
        cls,
        rule: RiskRuleType,
        reason: str,
        current: Optional[Decimal] = None,
        threshold: Optional[Decimal] = None,
        **metadata
    ) -> RiskCheckResult:
        """Create block result"""
        return cls(
            allowed=False,
            action=RiskAction.BLOCK,
            triggered_rule=rule,
            reason=reason,
            current_value=current,
            threshold=threshold,
            metadata=metadata
        )
    
    @classmethod
    def reduce(
        cls,
        rule: RiskRuleType,
        reason: str,
        reduction_pct: Decimal = dec("50"),
        **metadata
    ) -> RiskCheckResult:
        """Create reduce result"""
        return cls(
            allowed=True,  # Still allowed but reduced
            action=RiskAction.REDUCE,
            triggered_rule=rule,
            reason=reason,
            metadata={"reduction_pct": str(reduction_pct), **metadata}
        )
    
    @classmethod
    def warn(
        cls,
        rule: RiskRuleType,
        reason: str,
        **metadata
    ) -> RiskCheckResult:
        """Create warning result"""
        return cls(
            allowed=True,
            action=RiskAction.WARN,
            triggered_rule=rule,
            reason=reason,
            metadata=metadata
        )


# ============= STORAGE PROTOCOLS =============

@runtime_checkable
class TradesRepository(Protocol):
    """Protocol for trades storage"""
    
    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        """Count orders in last N minutes"""
        ...
    
    def daily_turnover_quote(self, symbol: str) -> Decimal:
        """Get daily turnover in quote currency"""
        ...
    
    def get_loss_streak(self, symbol: str) -> int:
        """Get current loss streak"""
        ...
    
    def calculate_drawdown_pct(self, symbol: str) -> Decimal:
        """Calculate current drawdown percentage"""
        ...
    
    def get_daily_pnl(self, symbol: str) -> Decimal:
        """Get today's PnL"""
        ...
    
    def get_last_trade_time(self, symbol: str) -> Optional[datetime]:
        """Get timestamp of last trade"""
        ...


@runtime_checkable
class PositionsRepository(Protocol):
    """Protocol for positions storage"""
    
    def get_position_size(self, symbol: str) -> Decimal:
        """Get current position size"""
        ...
    
    def has_open_position(self, symbol: str) -> bool:
        """Check if there's an open position"""
        ...


# ============= RISK CONFIGURATION =============

@dataclass(frozen=True)
class RiskConfig:
    """Risk management configuration"""
    
    # Critical limits (force BLOCK)
    loss_streak_limit: int = 3
    max_drawdown_pct: Decimal = dec("10.0")
    daily_loss_limit_quote: Decimal = dec("100.0")
    max_orders_per_day: int = 100
    max_turnover_quote_per_day: Decimal = dec("10000.0")
    
    # Soft limits (REDUCE or WARN)
    cooldown_seconds: int = 60
    max_spread_pct: Decimal = dec("0.5")
    
    # Monitoring limits (WARN only)
    max_orders_5m: int = 5
    max_turnover_5m_quote: Decimal = dec("1000.0")
    
    # Correlation groups (symbols that should not be traded together)
    correlation_groups: list[list[str]] = field(default_factory=list)
    
    @classmethod
    def from_settings(cls, settings: any) -> RiskConfig:
        """Create config from settings object"""
        # Parse correlation groups from string format
        groups_str = getattr(settings, "RISK_ANTI_CORR_GROUPS", "")
        groups = []
        if groups_str:
            try:
                # Format: "BTC/USDT|ETH/USDT;XRP/USDT|ADA/USDT"
                for group_str in groups_str.split(";"):
                    if group_str:
                        group = [s.strip() for s in group_str.split("|")]
                        if group:
                            groups.append(group)
            except Exception as e:
                _log.warning(f"Failed to parse correlation groups: {e}")
        
        return cls(
            # Critical limits
            loss_streak_limit=getattr(settings, "RISK_LOSS_STREAK_COUNT", 3),
            max_drawdown_pct=dec(str(getattr(settings, "RISK_MAX_DRAWDOWN_PCT", 10.0))),
            daily_loss_limit_quote=dec(str(getattr(settings, "RISK_DAILY_LOSS_LIMIT_QUOTE", 100.0))),
            max_orders_per_day=getattr(settings, "SAFETY_MAX_ORDERS_PER_DAY", 100),
            max_turnover_quote_per_day=dec(str(getattr(settings, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 10000.0))),
            
            # Soft limits
            cooldown_seconds=getattr(settings, "soft_risk", {}).COOLDOWN_SEC if hasattr(settings, "soft_risk") else 60,
            max_spread_pct=dec(str(getattr(settings, "soft_risk", {}).MAX_SPREAD_PCT if hasattr(settings, "soft_risk") else 0.5)),
            
            # Monitoring
            max_orders_5m=getattr(settings, "soft_risk", {}).MAX_ORDERS_5M if hasattr(settings, "soft_risk") else 5,
            max_turnover_5m_quote=dec(str(getattr(settings, "soft_risk", {}).MAX_TURNOVER_5M_QUOTE if hasattr(settings, "soft_risk") else 1000.0)),
            
            # Correlation
            correlation_groups=groups
        )


# ============= BASE RISK RULE =============

class BaseRiskRule:
    """Base class for risk rules"""
    
    def check(
        self,
        symbol: str,
        trades_repo: Optional[TradesRepository] = None,
        positions_repo: Optional[PositionsRepository] = None,
        **kwargs
    ) -> RiskCheckResult:
        """Check if rule is violated"""
        raise NotImplementedError


# ============= CRITICAL RULES (BLOCK) =============

class LossStreakRule(BaseRiskRule):
    """Block trading after N consecutive losses"""
    
    def __init__(self, limit: int):
        self.limit = limit
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            streak = trades_repo.get_loss_streak(symbol)
            if streak >= self.limit:
                return RiskCheckResult.block(
                    rule=RiskRuleType.LOSS_STREAK,
                    reason=f"Loss streak {streak} >= {self.limit}",
                    current=dec(str(streak)),
                    threshold=dec(str(self.limit))
                )
        except Exception as e:
            _log.error(f"Loss streak check failed: {e}")
        
        return RiskCheckResult.allow()


class MaxDrawdownRule(BaseRiskRule):
    """Block trading when drawdown exceeds limit"""
    
    def __init__(self, max_pct: Decimal):
        self.max_pct = max_pct
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.max_pct <= 0:
            return RiskCheckResult.allow()
        
        try:
            drawdown = trades_repo.calculate_drawdown_pct(symbol)
            if drawdown >= self.max_pct:
                return RiskCheckResult.block(
                    rule=RiskRuleType.MAX_DRAWDOWN,
                    reason=f"Drawdown {drawdown}% >= {self.max_pct}%",
                    current=drawdown,
                    threshold=self.max_pct
                )
        except Exception as e:
            _log.error(f"Drawdown check failed: {e}")
        
        return RiskCheckResult.allow()


class DailyLossRule(BaseRiskRule):
    """Block trading when daily loss exceeds limit"""
    
    def __init__(self, limit_quote: Decimal):
        self.limit = limit_quote
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            daily_pnl = trades_repo.get_daily_pnl(symbol)
            if daily_pnl < -self.limit:
                return RiskCheckResult.block(
                    rule=RiskRuleType.DAILY_LOSS,
                    reason=f"Daily loss {daily_pnl} exceeds limit {-self.limit}",
                    current=abs(daily_pnl),
                    threshold=self.limit
                )
        except Exception as e:
            _log.error(f"Daily loss check failed: {e}")
        
        return RiskCheckResult.allow()


class BudgetOrdersRule(BaseRiskRule):
    """Block trading when daily order count exceeds limit"""
    
    def __init__(self, limit: int):
        self.limit = limit
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            count = trades_repo.count_orders_last_minutes(symbol, 1440)  # 24 hours
            if count >= self.limit:
                return RiskCheckResult.block(
                    rule=RiskRuleType.BUDGET_ORDERS,
                    reason=f"Daily orders {count} >= {self.limit}",
                    current=dec(str(count)),
                    threshold=dec(str(self.limit))
                )
        except Exception as e:
            _log.error(f"Budget orders check failed: {e}")
        
        return RiskCheckResult.allow()


class BudgetTurnoverRule(BaseRiskRule):
    """Block trading when daily turnover exceeds limit"""
    
    def __init__(self, limit_quote: Decimal):
        self.limit = limit_quote
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            turnover = trades_repo.daily_turnover_quote(symbol)
            if turnover >= self.limit:
                return RiskCheckResult.block(
                    rule=RiskRuleType.BUDGET_TURNOVER,
                    reason=f"Daily turnover {turnover} >= {self.limit}",
                    current=turnover,
                    threshold=self.limit
                )
        except Exception as e:
            _log.error(f"Budget turnover check failed: {e}")
        
        return RiskCheckResult.allow()


# ============= SOFT RULES (REDUCE/WARN) =============

class CooldownRule(BaseRiskRule):
    """Enforce cooldown period between trades"""
    
    def __init__(self, cooldown_seconds: int):
        self.cooldown = cooldown_seconds
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.cooldown <= 0:
            return RiskCheckResult.allow()
        
        try:
            last_trade_time = trades_repo.get_last_trade_time(symbol)
            if last_trade_time:
                elapsed = (datetime.utcnow() - last_trade_time).total_seconds()
                if elapsed < self.cooldown:
                    remaining = self.cooldown - elapsed
                    return RiskCheckResult.reduce(
                        rule=RiskRuleType.COOLDOWN,
                        reason=f"Cooldown active ({remaining:.0f}s remaining)",
                        reduction_pct=dec("100"),  # Full reduction = skip
                        remaining_seconds=remaining
                    )
        except Exception as e:
            _log.error(f"Cooldown check failed: {e}")
        
        return RiskCheckResult.allow()


class SpreadCapRule(BaseRiskRule):
    """Reduce position when spread is too high"""
    
    def __init__(self, max_spread_pct: Decimal, spread_provider: Optional[callable] = None):
        self.max_spread = max_spread_pct
        self.spread_provider = spread_provider
    
    def check(self, symbol: str, **kwargs) -> RiskCheckResult:
        if not self.spread_provider or self.max_spread <= 0:
            return RiskCheckResult.allow()
        
        try:
            current_spread = self.spread_provider(symbol)
            if current_spread > self.max_spread:
                # Reduce position size proportionally
                reduction = min(dec("75"), (current_spread / self.max_spread - 1) * 100)
                return RiskCheckResult.reduce(
                    rule=RiskRuleType.SPREAD_CAP,
                    reason=f"Spread {current_spread:.2f}% > {self.max_spread}%",
                    reduction_pct=reduction,
                    current_spread=current_spread
                )
        except Exception as e:
            _log.error(f"Spread check failed: {e}")
        
        return RiskCheckResult.allow()


class CorrelationRule(BaseRiskRule):
    """Warn about correlated positions"""
    
    def __init__(self, groups: list[list[str]]):
        self.groups = groups
    
    def check(
        self,
        symbol: str,
        positions_repo: Optional[PositionsRepository] = None,
        **kwargs
    ) -> RiskCheckResult:
        if not positions_repo or not self.groups:
            return RiskCheckResult.allow()
        
        try:
            # Find which group this symbol belongs to
            for group in self.groups:
                if symbol in group:
                    # Check if any other symbol in group has position
                    for other_symbol in group:
                        if other_symbol != symbol and positions_repo.has_open_position(other_symbol):
                            return RiskCheckResult.warn(
                                rule=RiskRuleType.CORRELATION,
                                reason=f"Correlated position exists: {other_symbol}",
                                correlated_symbol=other_symbol
                            )
        except Exception as e:
            _log.error(f"Correlation check failed: {e}")
        
        return RiskCheckResult.allow()


# ============= MONITORING RULES (WARN) =============

class Orders5MinuteRule(BaseRiskRule):
    """Monitor order frequency"""
    
    def __init__(self, limit: int):
        self.limit = limit
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            count = trades_repo.count_orders_last_minutes(symbol, 5)
            if count >= self.limit:
                return RiskCheckResult.warn(
                    rule=RiskRuleType.ORDERS_5M,
                    reason=f"High order frequency: {count} in 5min",
                    count=count
                )
        except Exception as e:
            _log.error(f"5min orders check failed: {e}")
        
        return RiskCheckResult.allow()


class Turnover5MinuteRule(BaseRiskRule):
    """Monitor turnover rate"""
    
    def __init__(self, limit_quote: Decimal):
        self.limit = limit_quote
    
    def check(self, symbol: str, trades_repo: Optional[TradesRepository] = None, **kwargs) -> RiskCheckResult:
        if not trades_repo or self.limit <= 0:
            return RiskCheckResult.allow()
        
        try:
            # This would need a method to get 5-minute turnover
            # For now, just return allow
            pass
        except Exception as e:
            _log.error(f"5min turnover check failed: {e}")
        
        return RiskCheckResult.allow()


# ============= MAIN RISK MANAGER =============

class RiskManager:
    """
    Aggregates all risk rules and evaluates trading decisions.
    Pure domain logic - no side effects, returns structured results.
    """
    
    def __init__(self, config: RiskConfig):
        self.config = config
        
        # Critical rules (BLOCK)
        self.critical_rules = [
            LossStreakRule(config.loss_streak_limit),
            MaxDrawdownRule(config.max_drawdown_pct),
            DailyLossRule(config.daily_loss_limit_quote),
            BudgetOrdersRule(config.max_orders_per_day),
            BudgetTurnoverRule(config.max_turnover_quote_per_day),
        ]
        
        # Soft rules (REDUCE/WARN)
        self.soft_rules = [
            CooldownRule(config.cooldown_seconds),
            SpreadCapRule(config.max_spread_pct),
            CorrelationRule(config.correlation_groups),
        ]
        
        # Monitoring rules (WARN)
        self.monitoring_rules = [
            Orders5MinuteRule(config.max_orders_5m),
            Turnover5MinuteRule(config.max_turnover_5m_quote),
        ]
    
    def check_trade(
        self,
        symbol: str,
        side: str,
        amount: Decimal,
        trace_id: str,
        trades_repo: Optional[TradesRepository] = None,
        positions_repo: Optional[PositionsRepository] = None,
        spread_provider: Optional[Callable[[str], Decimal]] = None
    ) -> RiskCheckResult:
        """
        Check if trade is allowed according to all risk rules.
        
        Returns structured result with action to take.
        Application layer decides how to handle the result.
        """
        
        # Check critical rules first (can BLOCK)
        for rule in self.critical_rules:
            result = rule.check(
                symbol=symbol,
                trades_repo=trades_repo,
                positions_repo=positions_repo
            )
            if result.action == RiskAction.BLOCK:
                _log.warning(
                    f"Trade blocked by {result.triggered_rule}",
                    extra={
                        "trace_id": trace_id,
                        "symbol": symbol,
                        "reason": result.reason,
                        "rule": result.triggered_rule.value if result.triggered_rule else None
                    }
                )
                return result
        
        # Check soft rules (can REDUCE)
        reduction_pct = dec("0")
        soft_warnings = []
        
        for rule in self.soft_rules:
            if isinstance(rule, SpreadCapRule) and spread_provider:
                # Pass custom spread provider if available
                rule.spread_provider = spread_provider
            
            result = rule.check(
                symbol=symbol,
                trades_repo=trades_repo,
                positions_repo=positions_repo
            )
            
            if result.action == RiskAction.REDUCE:
                # Accumulate reductions
                rule_reduction = dec(result.metadata.get("reduction_pct", "0"))
                reduction_pct = max(reduction_pct, rule_reduction)
                soft_warnings.append(result.reason)
        
        # If we have reductions, return REDUCE result
        if reduction_pct > 0:
            return RiskCheckResult.reduce(
                rule=RiskRuleType.SPREAD_CAP,  # Primary rule
                reason="; ".join(soft_warnings),
                reduction_pct=reduction_pct
            )
        
        # Check monitoring rules (WARN only)
        for rule in self.monitoring_rules:
            result = rule.check(
                symbol=symbol,
                trades_repo=trades_repo,
                positions_repo=positions_repo
            )
            if result.action == RiskAction.WARN:
                _log.info(
                    f"Risk warning: {result.reason}",
                    extra={"trace_id": trace_id, "symbol": symbol}
                )
                # Continue checking, warnings don't block
        
        # All checks passed
        return RiskCheckResult.allow()
    
    def can_execute(
        self,
        symbol: str,
        trades_repo: Optional[TradesRepository] = None,
        positions_repo: Optional[PositionsRepository] = None
    ) -> bool:
        """
        Quick check if trade can be executed.
        Returns bool for backward compatibility.
        """
        # Only check critical rules for quick decision
        for rule in self.critical_rules:
            result = rule.check(
                symbol=symbol,
                trades_repo=trades_repo,
                positions_repo=positions_repo
            )
            if result.action == RiskAction.BLOCK:
                return False
        return True


# ============= EXPORT =============

__all__ = [
    "RiskManager",
    "RiskConfig",
    "RiskCheckResult",
    "RiskAction",
    "RiskRuleType",
    "TradesRepository",
    "PositionsRepository",
]