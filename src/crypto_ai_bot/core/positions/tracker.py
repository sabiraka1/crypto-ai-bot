from __future__ import annotations
from typing import Any, Dict, List, Optional
from decimal import Decimal, InvalidOperation

from crypto_ai_bot.utils import metrics

def _to_dec(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

class PositionTracker:
    """
    Лёгкий трекер для экспозиции и PnL (реализованный).
    Никаких вызовов брокера/HTTP; всё берём из репозиториев.
    """

    def __init__(self, positions_repo, trades_repo):
        self.positions_repo = positions_repo
        self.trades_repo = trades_repo

    # --- публичные методы, используемые из app/telegram.py и server.py ---

    def get_exposure_units(self) -> Decimal:
        """
        Сумма |size| по открытым позициям (в базовой валюте).
        """
        total = Decimal("0")
        try:
            opens: List[Dict[str, Any]] = self.positions_repo.get_open() or []
        except Exception:
            opens = []
        for p in opens:
            total += _to_dec(p.get("size")).copy_abs()
        return total

    def get_pnl(self) -> Decimal:
        """
        Реализованный PnL по полю trades.pnl (если есть), иначе 0.
        """
        realized = Decimal("0")
        try:
            # метод list_recent/ list_all — зависит от реализации. Пытаемся аккуратно.
            rows: List[Dict[str, Any]] = []
            if hasattr(self.trades_repo, "list_all"):
                rows = self.trades_repo.list_all() or []
            elif hasattr(self.trades_repo, "list_recent"):
                rows = self.trades_repo.list_recent(limit=10000) or []
        except Exception:
            rows = []
        for t in rows:
            realized += _to_dec(t.get("pnl"))
        return realized

    def update_metrics(self) -> None:
        """
        Обновляет Prometheus-гейджи.
        """
        exp = self.get_exposure_units()
        pnl = self.get_pnl()
        metrics.observe("positions_exposure_gauge", float(exp), {"unit": "base"})
        metrics.observe("positions_pnl_gauge", float(pnl), {"currency": "base"})
