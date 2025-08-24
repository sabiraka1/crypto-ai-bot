from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from .loss_streak import _fifo_closed_pnls_today  # переиспользуем реализацию
from ...storage.facade import Storage


def compute_today_drawdown_quote(storage: Storage, symbol: str) -> Decimal:
    """
    Консервативная дневная просадка по реализованному PnL: сумма отрицательных закрытий за день.
    Возвращает ≤ 0 (или 0, если просадки нет).
    """
    pnls: List[Decimal] = _fifo_closed_pnls_today(storage, symbol)
    dd = sum((p for p in pnls if p < 0), Decimal("0"))
    return dd
