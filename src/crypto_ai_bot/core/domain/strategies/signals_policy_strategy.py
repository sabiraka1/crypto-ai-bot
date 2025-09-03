from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseStrategy, Decision, MarketData, StrategyContext

# ДћЕёДћВѕДћВґГ‘ВЃДћВёГ‘ВЃГ‘вЂљДћВµДћВјДћВ° signals (ДћВіДћВѕГ‘вЂљДћВѕДћВІДћВ°Г‘ВЏ, ДћВЅДћВѕ Г‘в‚¬ДћВ°ДћВЅДћВµДћВµ ДћВЅДћВµ ДћВІДћВєДћВ»Г‘ВЋГ‘вЂЎГ‘вЂДћВЅДћВЅДћВ°Г‘ВЏ ДћВІ Г‘в‚¬ДћВ°ДћВЅГ‘вЂљДћВ°ДћВ№ДћВј)
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
    ДћВђДћВґДћВ°ДћВїГ‘вЂљДћВµГ‘в‚¬, ДћВєДћВѕГ‘вЂљДћВѕГ‘в‚¬Г‘вЂ№ДћВ№:
      1) Г‘ВЃГ‘вЂљГ‘в‚¬ДћВѕДћВёГ‘вЂљ Г‘ВЃДћВїДћВёГ‘ВЃДћВѕДћВє Г‘ВЃДћВёДћВіДћВЅДћВ°ДћВ»ДћВѕДћВІ ДћВёДћВ· MarketData (build_signals)
      2) ДћВ°ДћВіГ‘в‚¬ДћВµДћВіДћВёГ‘в‚¬Г‘Ж’ДћВµГ‘вЂљ ДћВёГ‘вЂ¦ (fuse_signals)
      3) ДћВїГ‘в‚¬ДћВёДћВЅДћВёДћВјДћВ°ДћВµГ‘вЂљ Г‘в‚¬ДћВµГ‘Л†ДћВµДћВЅДћВёДћВµ ДћВїДћВѕ ДћВ·ДћВ°ДћВґДћВ°ДћВЅДћВЅДћВѕДћВ№ ДћВїДћВѕДћВ»ДћВёГ‘вЂљДћВёДћВєДћВµ (SignalsPolicy)
    """

    def __init__(self, *, policy: str = "conservative") -> None:
        self.policy_name = policy
        self.score = 1.0  # ДћВґДћВ»Г‘ВЏ weighted-Г‘в‚¬ДћВµДћВ¶ДћВёДћВјДћВ° ДћВјДћВµДћВЅДћВµДћВґДћВ¶ДћВµГ‘в‚¬ДћВ°

    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # ДћЕёГ‘в‚¬ДћВѕДћВІДћВµГ‘в‚¬Г‘ВЏДћВµДћВј Г‘вЂЎГ‘вЂљДћВѕ ДћВјДћВѕДћВґГ‘Ж’ДћВ»ДћВё ДћВ±Г‘вЂ№ДћВ»ДћВё ДћВёДћВјДћВїДћВѕГ‘в‚¬Г‘вЂљДћВёГ‘в‚¬ДћВѕДћВІДћВ°ДћВЅГ‘вЂ№
        if SignalsPolicy is None or fuse_signals is None or build_signals is None:
            return Decision(action="hold", reason="signals_subsystem_unavailable")

        # ДћВЈДћВїГ‘в‚¬ДћВѕГ‘вЂ°ДћВµДћВЅДћВЅДћВ°Г‘ВЏ Г‘в‚¬ДћВµДћВ°ДћВ»ДћВёДћВ·ДћВ°Г‘вЂ ДћВёГ‘ВЏ ДћВ±ДћВµДћВ· build_signals (Г‘вЂљДћВ°ДћВє ДћВєДћВ°ДћВє ДћВѕДћВЅ Г‘вЂљГ‘в‚¬ДћВµДћВ±Г‘Ж’ДћВµГ‘вЂљ ДћВґГ‘в‚¬Г‘Ж’ДћВіДћВёДћВµ ДћВїДћВ°Г‘в‚¬ДћВ°ДћВјДћВµГ‘вЂљГ‘в‚¬Г‘вЂ№)
        # ДћЛњГ‘ВЃДћВїДћВѕДћВ»Г‘Е’ДћВ·Г‘Ж’ДћВµДћВј ДћВґДћВ°ДћВЅДћВЅГ‘вЂ№ДћВµ ДћВёДћВ· MarketData ДћВЅДћВ°ДћВїГ‘в‚¬Г‘ВЏДћВјГ‘Ж’Г‘ВЋ
        ticker = await md.get_ticker(ctx.symbol)
        features = {
            "last": ticker.get("last", 0),
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "spread_pct": ((ticker.get("ask", 0) - ticker.get("bid", 0)) / ticker.get("last", 1)) * 100
            if ticker.get("last", 0) > 0
            else 0,
        }

        # ДћВЎДћВѕДћВ·ДћВґДћВ°ДћВµДћВј Г‘ВЌДћВєДћВ·ДћВµДћВјДћВїДћВ»Г‘ВЏГ‘в‚¬ ДћВїДћВѕДћВ»ДћВёГ‘вЂљДћВёДћВєДћВё
        try:
            policy = SignalsPolicy()
            if hasattr(policy, "decide"):
                decision, score, explain = policy.decide(features)
            else:
                # ДћвЂўГ‘ВЃДћВ»ДћВё ДћВјДћВµГ‘вЂљДћВѕДћВґДћВ° decide ДћВЅДћВµГ‘вЂљ, ДћВІДћВѕДћВ·ДћВІГ‘в‚¬ДћВ°Г‘вЂ°ДћВ°ДћВµДћВј hold
                return Decision(action="hold", reason="policy_decide_not_found")
        except Exception as e:
            return Decision(action="hold", reason=f"policy_error:{e}")

        return Decision(action=decision, confidence=score, reason=str(explain or ""))
