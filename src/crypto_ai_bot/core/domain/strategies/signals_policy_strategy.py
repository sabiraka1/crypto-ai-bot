from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseStrategy, Decision, MarketData, StrategyContext


# ĞŸĞ¾Ğ´ÑĞ¸ÑÑ‚ĞµĞ¼Ğ° signals (Ğ³Ğ¾Ñ‚Ğ¾Ğ²Ğ°Ñ, Ğ½Ğ¾ Ñ€Ğ°Ğ½ĞµĞµ Ğ½Ğµ Ğ²ĞºĞ»ÑÑ‡Ñ‘Ğ½Ğ½Ğ°Ñ Ğ² Ñ€Ğ°Ğ½Ñ‚Ğ°Ğ¹Ğ¼)
if TYPE_CHECKING:
    from crypto_ai_bot.core.domain.signals._build import build_signals
    from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
    from crypto_ai_bot.core.domain.signals.policy import Policy as SignalsPolicy
else:
    try:
        from crypto_ai_bot.core.domain.signals._build import build_signals
        from crypto_ai_bot.core.domain.signals._fusion import fuse_signals
        from crypto_ai_bot.core.domain.signals.policy import Policy as SignalsPolicy
    except ImportError:
        SignalsPolicy = None
        fuse_signals = None
        build_signals = None


class SignalsPolicyStrategy(BaseStrategy):
    """
    ĞĞ´Ğ°Ğ¿Ñ‚ĞµÑ€, ĞºĞ¾Ñ‚Ğ¾Ñ€Ñ‹Ğ¹:
      1) ÑÑ‚Ñ€Ğ¾Ğ¸Ñ‚ ÑĞ¿Ğ¸ÑĞ¾Ğº ÑĞ¸Ğ³Ğ½Ğ°Ğ»Ğ¾Ğ² Ğ¸Ğ· MarketData (build_signals)
      2) Ğ°Ğ³Ñ€ĞµĞ³Ğ¸Ñ€ÑƒĞµÑ‚ Ğ¸Ñ… (fuse_signals)
      3) Ğ¿Ñ€Ğ¸Ğ½Ğ¸Ğ¼Ğ°ĞµÑ‚ Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ Ğ¿Ğ¾ Ğ·Ğ°Ğ´Ğ°Ğ½Ğ½Ğ¾Ğ¹ Ğ¿Ğ¾Ğ»Ğ¸Ñ‚Ğ¸ĞºĞµ (SignalsPolicy)
    """

    def __init__(self, *, policy: str = "conservative") -> None:
        self.policy_name = policy
        self.score = 1.0  # Ğ´Ğ»Ñ weighted-Ñ€ĞµĞ¶Ğ¸Ğ¼Ğ° Ğ¼ĞµĞ½ĞµĞ´Ğ¶ĞµÑ€Ğ°

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # ĞŸÑ€Ğ¾Ğ²ĞµÑ€ÑĞµĞ¼ Ñ‡Ñ‚Ğ¾ Ğ¼Ğ¾Ğ´ÑƒĞ»Ğ¸ Ğ±Ñ‹Ğ»Ğ¸ Ğ¸Ğ¼Ğ¿Ğ¾Ñ€Ñ‚Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ñ‹
        if SignalsPolicy is None or fuse_signals is None or build_signals is None:
            return Decision(action="hold", reason="signals_subsystem_unavailable")

        # Ğ£Ğ¿Ñ€Ğ¾Ñ‰ĞµĞ½Ğ½Ğ°Ñ Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ñ Ğ±ĞµĞ· build_signals (Ñ‚Ğ°Ğº ĞºĞ°Ğº Ğ¾Ğ½ Ñ‚Ñ€ĞµĞ±ÑƒĞµÑ‚ Ğ´Ñ€ÑƒĞ³Ğ¸Ğµ Ğ¿Ğ°Ñ€Ğ°Ğ¼ĞµÑ‚Ñ€Ñ‹)
        # Ğ˜ÑĞ¿Ğ¾Ğ»ÑŒĞ·ÑƒĞµĞ¼ Ğ´Ğ°Ğ½Ğ½Ñ‹Ğµ Ğ¸Ğ· MarketData Ğ½Ğ°Ğ¿Ñ€ÑĞ¼ÑƒÑ
        ticker = await md.get_ticker(ctx.symbol)
        features = {
            "last": ticker.get("last", 0),
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "spread_pct": ((ticker.get("ask", 0) - ticker.get("bid", 0)) / ticker.get("last", 1)) * 100 if ticker.get("last", 0) > 0 else 0,
        }

        # Ğ¡Ğ¾Ğ·Ğ´Ğ°ĞµĞ¼ ÑĞºĞ·ĞµĞ¼Ğ¿Ğ»ÑÑ€ Ğ¿Ğ¾Ğ»Ğ¸Ñ‚Ğ¸ĞºĞ¸
        try:
            policy = SignalsPolicy()
            if hasattr(policy, 'decide'):
                decision, score, explain = policy.decide(features)
            else:
                # Ğ•ÑĞ»Ğ¸ Ğ¼ĞµÑ‚Ğ¾Ğ´Ğ° decide Ğ½ĞµÑ‚, Ğ²Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµĞ¼ hold
                return Decision(action="hold", reason="policy_decide_not_found")
        except Exception as e:
            return Decision(action="hold", reason=f"policy_error:{e}")

        return Decision(action=decision, confidence=score, reason=str(explain or ""))
