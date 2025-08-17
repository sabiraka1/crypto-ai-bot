# src/crypto_ai_bot/utils/percentiles.py
from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque
from typing import Deque, List, Tuple, Optional


class RollingQuantiles:
    """
    Кольцевое окно с поддержкой p95/p99.
    Вставка/удаление O(n) (за счёт поддержания отсортированного массива),
    но при окне 256..1024 — этого достаточно и просто.
    """

    __slots__ = ("_window", "_sorted", "_maxlen")

    def __init__(self, maxlen: int = 512) -> None:
        if maxlen < 8:
            maxlen = 8
        self._maxlen: int = int(maxlen)
        self._window: Deque[float] = deque()
        self._sorted: List[float] = []

    def add(self, value: float) -> None:
        # вставка в конец очереди
        self._window.append(value)
        # вставка в отсортированный массив
        insort(self._sorted, value)

        # если переполнились — удаляем слева и из отсортированного массива
        if len(self._window) > self._maxlen:
            old = self._window.popleft()
            idx = bisect_left(self._sorted, old)
            if 0 <= idx < len(self._sorted):
                # с учётом дублей удаляем первый найденный
                del self._sorted[idx]

    def __len__(self) -> int:
        return len(self._window)

    def quantile(self, q: float) -> Optional[float]:
        """
        Возвращает квантили по ближайшему рангу.
        q в [0,1], например 0.95, 0.99
        """
        n = len(self._sorted)
        if n == 0:
            return None
        if q <= 0:
            return float(self._sorted[0])
        if q >= 1:
            return float(self._sorted[-1])
        # nearest-rank
        rank = int(round(q * (n - 1)))
        return float(self._sorted[rank])

    def p95(self) -> Optional[float]:
        return self.quantile(0.95)

    def p99(self) -> Optional[float]:
        return self.quantile(0.99)
