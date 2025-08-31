# src/crypto_ai_bot/core/domain/strategies/manager.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Tuple, Optional

from .base import BaseStrategy, StrategyContext, MarketData
from .ema_cross import EmaCrossStrategy
from .rsi_momentum import RSIMomentumStrategy
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrStrategy
from .signals_policy_strategy import SignalsPolicyStrategy


@dataclass
class Decision:
    action: str  # 'buy' | 'sell' | 'hold'
    explain: str
    score: float = 1.0


class StrategyManager:
    """
    Агрегатор стратегий с поддержкой Regime-политики.
    Параметры (из settings):
      - STRATEGY_SET: список стратегий через запятую (по умолчанию: ema_cross,ema_atr,signals_policy)
      - STRATEGY_MODE: first|vote|weighted (по умолчанию: first)
      - REGIME_ENABLED: 0|1 (по умолчанию: 1)
      - REGIME_BLOCK_BUY: 0|1 (по умолчанию: 1) — в risk_off блокируем новые buy
      - REGIME_WEIGHT_MULT_RISK_OFF: float (по умолчанию: 0.5) — для weighted уменьшаем общий вес
    """

    def __init__(
        self,
        *,
        settings: Any,
        strategies: Iterable[BaseStrategy] | None = None,
        regime_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self._settings = settings
        self._mode: str = str(getattr(settings, "STRATEGY_MODE", "first") or "first").lower()
        self._strategies: List[BaseStrategy] = list(strategies or [])
        self._regime_provider = regime_provider
        if not self._strategies:
            self._strategies = list(self._build_from_settings(settings))

    def _build_from_settings(self, settings: Any) -> Iterable[BaseStrategy]:
        names = str(getattr(settings, "STRATEGY_SET", "ema_cross,ema_atr,signals_policy") or "ema_cross,ema_atr,signals_policy")
        for name in [x.strip().lower() for x in names.split(",") if x.strip()]:
            if name == "ema_cross":
                yield EmaCrossStrategy()
            elif name == "rsi_momentum":
                yield RSIMomentumStrategy()
            elif name == "bollinger_bands":
                yield BollingerBandsStrategy()
            elif name == "ema_atr":
                yield EmaAtrStrategy()
            elif name in ("signals", "signals_policy"):
                yield SignalsPolicyStrategy()

    def _apply_regime_first(self, action: str, explain: str) -> Tuple[str, str]:
        if not int(getattr(self._settings, "REGIME_ENABLED", 1) or 1):
            return action, explain
        regime = self._regime_provider() if self._regime_provider else "range"
        if regime == "risk_off" and int(getattr(self._settings, "REGIME_BLOCK_BUY", 1) or 1):
            if action == "buy":
                return "hold", f"{explain}|regime:block_buy"
        return action, explain

    def _regime_weight_multiplier(self) -> float:
        if not int(getattr(self._settings, "REGIME_ENABLED", 1) or 1):
            return 1.0
        regime = self._regime_provider() if self._regime_provider else "range"
        if regime == "risk_off":
            return float(getattr(self._settings, "REGIME_WEIGHT_MULT_RISK_OFF", 0.5) or 0.5)
        return 1.0

    async def decide(self, *, ctx: StrategyContext, md: MarketData) -> Tuple[str, str]:
        if self._mode not in ("first", "vote", "weighted"):
            self._mode = "first"

        if self._mode == "first":
            for s in self._strategies:
                action, explain = await s.decide(ctx=ctx, md=md)
                if action in ("buy", "sell"):
                    return self._apply_regime_first(action, explain)
            return "hold", "all_hold"

        # собираем все решения
        votes: List[Decision] = []
        for s in self._strategies:
            action, explain = await s.decide(ctx=ctx, md=md)
            score = float(getattr(s, "score", 1.0) or 1.0)
            votes.append(Decision(action=action, explain=explain, score=score))

        if self._mode == "vote":
            buy = sum(1 for v in votes if v.action == "buy")
            sell = sum(1 for v in votes if v.action == "sell")
            # применим простую блокировку buy при risk_off
            action = "buy" if buy > sell and buy > 0 else "sell" if sell > buy and sell > 0 else "hold"
            action, explain = (action, f"vote:{buy}>{sell}") if action != "hold" else ("hold", "vote_tie_or_all_hold")
            return self._apply_regime_first(action, explain)

        # weighted
        mult = self._regime_weight_multiplier()
        w_buy = sum(v.score for v in votes if v.action == "buy") * mult
        w_sell = sum(v.score for v in votes if v.action == "sell")
        if w_buy > w_sell and w_buy > 0:
            action, explain = ("buy", f"weighted:{w_buy:.3f}>{w_sell:.3f}")
            return self._apply_regime_first(action, explain)
        if w_sell > w_buy and w_sell > 0:
            return "sell", f"weighted:{w_sell:.3f}>{w_buy:.3f}"
        return "hold", "weighted_tie_or_all_hold"
