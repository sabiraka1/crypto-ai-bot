from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .base import BaseStrategy, MarketData, StrategyContext
from .bollinger_bands import BollingerBandsStrategy
from .ema_atr import EmaAtrConfig, EmaAtrStrategy
from .ema_cross import EmaCrossStrategy
from .rsi_momentum import RSIMomentumStrategy
from .signals_policy_strategy import SignalsPolicyStrategy


@dataclass
class Decision:
    action: str  # 'buy' | 'sell' | 'hold'
    explain: str
    score: float = 1.0


def _parse_scores(s: str) -> dict[str, float]:
    """
    Пример: "ema_cross:1.0,ema_atr:1.2,signals_policy:1.5"
    """
    out: dict[str, float] = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, val = part.split(":", 1)
        name = name.strip().lower()
        try:
            out[name] = float(val.strip())
        except Exception:
            continue
    return out


class StrategyManager:
    """
    Агрегатор стратегий с поддержкой Regime-политики и weighted-режима.
    Настройки:
      - STRATEGY_SET: "ema_cross,ema_atr,signals_policy"
      - STRATEGY_MODE: "first" | "vote" | "weighted"
      - STRATEGY_SCORES: "ema_cross:1.0,ema_atr:1.2"
      - REGIME_ENABLED, REGIME_BLOCK_BUY, REGIME_WEIGHT_MULT_RISK_OFF
    """

    def __init__(
        self,
        *,
        settings: Any,
        strategies: Iterable[BaseStrategy] | None = None,
        regime_provider: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings
        self._mode: str = str(getattr(settings, "STRATEGY_MODE", "first") or "first").lower()
        self._strategies: list[BaseStrategy] = list(strategies or [])
        self._regime_provider = regime_provider
        self._scores_map: dict[str, float] = _parse_scores(str(getattr(settings, "STRATEGY_SCORES", "") or ""))

        if not self._strategies:
            self._strategies = list(self._build_from_settings(settings))
        self._apply_scores()

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
                # Исправлено: создаём с конфигом
                cfg = EmaAtrConfig()
                yield EmaAtrStrategy(cfg)
            elif name in ("signals", "signals_policy"):
                yield SignalsPolicyStrategy()

    def _apply_scores(self) -> None:
        for s in self._strategies:
            key = type(s).__name__.replace("Strategy", "").lower()
            # допустим и по short-имени из списка
            for cand in (key,):
                if cand in self._scores_map:
                    try:
                        s.score = float(self._scores_map[cand])  # type: ignore[attr-defined]
                    except Exception:
                        pass

    def _apply_regime_first(self, action: str, explain: str) -> tuple[str, str]:
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

    async def decide(self, *, ctx: StrategyContext, md: MarketData) -> tuple[str, str]:
        if self._mode not in ("first", "vote", "weighted"):
            self._mode = "first"

        if self._mode == "first":
            for s in self._strategies:
                # Адаптер: если есть decide() - используем его, иначе generate()
                if hasattr(s, 'decide') and callable(s.decide):
                    action, explain = await s.decide(ctx=ctx, md=md)  # type: ignore
                else:
                    # Используем generate() и преобразуем Decision в (action, explain)
                    decision = await s.generate(ctx=ctx, md=md)
                    action = decision.action
                    explain = decision.reason
                
                if action in ("buy", "sell"):
                    return self._apply_regime_first(action, explain)
            return "hold", "all_hold"

        votes: list[Decision] = []
        for s in self._strategies:
            # Адаптер для совместимости
            if hasattr(s, 'decide') and callable(s.decide):
                action, explain = await s.decide(ctx=ctx, md=md)  # type: ignore
            else:
                decision = await s.generate(ctx=ctx, md=md)
                action = decision.action
                explain = decision.reason
            
            score = float(getattr(s, "score", 1.0) or 1.0)
            votes.append(Decision(action=action, explain=explain, score=score))

        if self._mode == "vote":
            buy = sum(1 for v in votes if v.action == "buy")
            sell = sum(1 for v in votes if v.action == "sell")
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