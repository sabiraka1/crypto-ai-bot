## `core/analytics/metrics.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from typing import Dict, List, Optional, Tuple
from ..storage.facade import Storage
@dataclass(frozen=True)
class PnLReport:
    realized_pnl: Decimal          # суммарный реализованный PnL в котируемой валюте (продажи - покупки)
    gross_buys: Decimal            # сколько потрачено на покупки (quote)
    gross_sells: Decimal           # сколько получено с продаж (quote)
    win_rate: float                # доля прибыльных SELL по отношению к последней equity-динамике
    trade_count: int               # количество закрытых сделок (строк в trades)
    sell_count: int                # количество SELL-сделок
    max_drawdown: Decimal          # максимальная просадка equity в абсолютных единицах quote
    sharpe_like: float             # упрощённый "шарп" на основе шагов equity (на сделку)
def compute_pnl(storage: Storage, *, symbol: Optional[str] = None) -> PnLReport:
    """Суммирует PnL на основе таблицы trades.
    Методика:
      - equity начинается с 0;
      - BUY уменьшает equity на `cost` (тратим quote);
      - SELL увеличивает equity на `cost` (получаем quote);
      - realized_pnl = последняя equity;
      - win_rate - доля SELL с положительным вкладом в equity относительно предыдущего значения;
      - max_drawdown - максимум (peak - equity) по траектории equity;
      - sharpe_like - среднее приращение equity / std приращений (на сделку), если std>0.
    """
    rows = storage.trades.list_recent(symbol=symbol, limit=10_000)
    rows.sort(key=lambda r: (r.ts_ms, r.id))
    equity = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    deltas: List[Decimal] = []
    gross_buys = Decimal("0")
    gross_sells = Decimal("0")
    sell_count = 0
    for r in rows:
        if r.status != "closed":
            continue
        if r.side == "buy":
            delta = -r.cost
            gross_buys += r.cost
        else:  # sell
            delta = r.cost
            gross_sells += r.cost
            sell_count += 1
        equity += delta
        deltas.append(delta)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    realized = equity
    sell_deltas = [d for (d, r) in zip(deltas, rows) if r.status == "closed" and r.side == "sell"]
    wins = sum(1 for d in sell_deltas if d > 0)
    wr = (wins / sell_count) if sell_count else 0.0
    n = len(deltas)
    if n >= 2:
        mean = sum(deltas, start=Decimal("0")) / Decimal(n)
        variance = sum((d - mean) ** 2 for d in deltas) / Decimal(n - 1)
        std = Decimal(variance).sqrt() if variance > 0 else Decimal("0")
        sharpe = float((mean / std) if std > 0 else Decimal("0"))
    else:
        sharpe = 0.0
    return PnLReport(
        realized_pnl=realized,
        gross_buys=gross_buys,
        gross_sells=gross_sells,
        win_rate=float(wr),
        trade_count=len([r for r in rows if r.status == "closed"]),
        sell_count=sell_count,
        max_drawdown=max_dd,
        sharpe_like=sharpe,
    )
def report_dict(storage: Storage, *, symbol: Optional[str] = None) -> Dict[str, object]:
    r = compute_pnl(storage, symbol=symbol)
    return {
        "realized_pnl": str(r.realized_pnl),
        "gross_buys": str(r.gross_buys),
        "gross_sells": str(r.gross_sells),
        "win_rate": r.win_rate,
        "trade_count": r.trade_count,
        "sell_count": r.sell_count,
        "max_drawdown": str(r.max_drawdown),
        "sharpe_like": r.sharpe_like,
    }