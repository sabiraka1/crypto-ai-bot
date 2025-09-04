from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TFWeights:
    """Weights for multi-timeframe aggregation (should sum ~1.0)."""

    w_15m: float = 0.40
    w_1h: float = 0.25
    w_4h: float = 0.20
    w_1d: float = 0.10
    w_1w: float = 0.05

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (self.w_15m, self.w_1h, self.w_4h, self.w_1d, self.w_1w)

    def total(self) -> float:
        """Сумма весов (для диагностики/метрик)."""
        t = self.w_15m + self.w_1h + self.w_4h + self.w_1d + self.w_1w
        return float(t)

    def normalized(self) -> TFWeights:
        """Вернёт новые веса, нормированные так, чтобы сумма была ровно 1.0."""
        t = self.total()
        if t <= 0:
            # крайний случай: возвращаем исходные (не ломаем поведение)
            return self
        return TFWeights(
            w_15m=self.w_15m / t,
            w_1h=self.w_1h / t,
            w_4h=self.w_4h / t,
            w_1d=self.w_1d / t,
            w_1w=self.w_1w / t,
        )
