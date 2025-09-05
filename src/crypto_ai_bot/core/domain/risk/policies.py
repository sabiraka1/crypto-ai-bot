"""Default risk policies and soft limits."""


class SoftRiskDefaults:
    """Soft risk limits (can be overridden via ENV)."""

    COOLDOWN_SEC = 60
    MAX_SPREAD_PCT = 0.5
    MAX_SLIPPAGE_PCT = 1.0
    MAX_ORDERS_5M = 5
    MAX_TURNOVER_5M_QUOTE = 1000
