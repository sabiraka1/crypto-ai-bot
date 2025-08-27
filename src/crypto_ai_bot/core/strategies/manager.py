from __future__ import annotations

from collections import defaultdict, Counter
from typing import Any, Dict, List, Tuple, Optional

from .base import BaseStrategy, StrategyContext, Decision
from .ema_cross import EmaCrossStrategy


class StrategyManager:
    """Менеджер стратегий с режимами:
       - 'first': использовать первую стратегию (совместимо по умолчанию)
       - 'vote':  простое голосование
       - 'weighted': взвешенное голосование (по накопленным «оценкам» решений)
    """

    def __init__(self, strategies: Optional[List[BaseStrategy]] = None) -> None:
        self.strategies: List[BaseStrategy] = strategies or [EmaCrossStrategy()]
        self._performance: Dict[str, List[float]] = defaultdict(list)
        self._weights: List[float] = self._initial_weights()

    def _initial_weights(self) -> List[float]:
        n = len(self.strategies)
        return [1.0 / n] * n if n else []

    def decide(
        self,
        *,
        symbol: str,
        exchange: str,
        context: Dict[str, Any],
        mode: str = "first",
    ) -> Tuple[Decision, Dict[str, Any]]:
        ctx = StrategyContext(symbol=symbol, exchange=exchange, data=context)

        if not self.strategies:
            return "hold", {"reason": "no_strategies"}

        if mode == "first":
            return self.strategies[0].decide(ctx)

        decisions: List[Decision] = []
        explains: List[Dict[str, Any]] = []
        for s in self.strategies:
            d, e = s.decide(ctx)
            decisions.append(d)
            explains.append(e)
            self._track(s.__name__ if hasattr(s, "__name__") else s.__class__.__name__, d)

        if mode == "vote":
            return self._majority(decisions, explains)

        if mode == "weighted":
            return self._weighted(decisions, explains)

        return "hold", {"reason": "unknown_mode"}

    def _majority(self, decisions: List[Decision], explains: List[Dict[str, Any]]) -> Tuple[Decision, Dict[str, Any]]:
        cnt = Counter(decisions)
        winner = cnt.most_common(1)[0][0]
        return winner, {"mode": "majority", "votes": dict(cnt), "winner": winner, "strategies": explains}

    def _weighted(self, decisions: List[Decision], explains: List[Dict[str, Any]]) -> Tuple[Decision, Dict[str, Any]]:
        w = self._current_weights()
        scores = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        for i, d in enumerate(decisions):
            scores[d] += w[i]
        winner = max(scores.items(), key=lambda x: x[1])[0]
        return winner, {"mode": "weighted", "scores": scores, "weights": w, "winner": winner, "strategies": explains}

    def _current_weights(self) -> List[float]:
        if not self._performance:
            return self._weights
        # простая нормализация по псевдо-шарпу из последних 100 «оценок»
        ws: List[float] = []
        names = [s.__class__.__name__ for s in self.strategies]
        for name in names:
            arr = self._performance.get(name, [])
            if len(arr) < 10:
                ws.append(1.0 / len(names))
            else:
                import statistics
                last = arr[-100:]
                mean = statistics.mean(last)
                std = statistics.stdev(last) if len(last) > 1 else 1.0
                sharpe = mean / std if std > 0 else 0.0
                ws.append(max(0.1, float(sharpe)))
        s = sum(ws)
        return [x / s for x in ws] if s > 0 else self._weights

    def _track(self, name: str, decision: Decision) -> None:
        score = {"buy": 1.0, "sell": -1.0, "hold": 0.0}.get(decision, 0.0)
        self._performance[name].append(score)
        if len(self._performance[name]) > 1000:
            self._performance[name] = self._performance[name][-1000:]

    def add_strategy(self, strategy: BaseStrategy) -> None:
        self.strategies.append(strategy)
        self._weights = self._initial_weights()

    def get_performance_report(self) -> Dict[str, Any]:
        names = [s.__class__.__name__ for s in self.strategies]
        weights = self._current_weights()
        rep: Dict[str, Any] = {}
        for i, name in enumerate(names):
            arr = self._performance.get(name, [])
            if arr:
                import statistics
                rep[name] = {
                    "trades": len(arr),
                    "win_rate": sum(1 for x in arr if x > 0) / len(arr),
                    "avg_return": statistics.mean(arr),
                    "current_weight": weights[i],
                }
        return rep
