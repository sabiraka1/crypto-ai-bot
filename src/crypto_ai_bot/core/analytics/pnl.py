from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Tuple

from ...utils.time import now_ms


@dataclass(frozen=True)
class PnLPoint:
    qty_base: Decimal
    avg_price: Decimal
    realized_quote: Decimal


def _utc_day_bounds_ms(ts_ms: int) -> Tuple[int, int]:
    ts = _dt.datetime.utcfromtimestamp(ts_ms / 1000.0)
    start = _dt.datetime(ts.year, ts.month, ts.day, tzinfo=_dt.timezone.utc)
    end = start + _dt.timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def get_today_bounds_utc(reference_ts_ms: int | None = None) -> Tuple[int, int]:
    """
    Возвращает [start_ms, end_ms) текущего UTC дня.
    """
    return _utc_day_bounds_ms(reference_ts_ms or now_ms())


def fifo_pnl(trades: Iterable[dict]) -> List[PnLPoint]:
    """
    Простой FIFO-расчёт по списку трейдов.
    Требуемые ключи трейда: side ('buy'|'sell'), amount (Decimal), cost (Decimal).
    cost — СУММА в quote (не price!).

    Возвращает серию PnLPoint с текущим количеством, сред. ценой и реализованным PnL (quote).
    """
    lots: List[Tuple[Decimal, Decimal]] = []  # (qty_base, avg_price_quote_per_base)
    realized = Decimal("0")
    series: List[PnLPoint] = []

    for t in trades:
        side = str(t.get("side", "")).lower()
        amt: Decimal = Decimal(str(t.get("amount", "0")))
        cost: Decimal = Decimal(str(t.get("cost", "0")))  # сумма в quote

        if amt <= 0:
            series.append(PnLPoint(
                qty_base=sum(q for q, _ in lots),
                avg_price=Decimal("0") if not lots else (sum(q * p for q, p in lots) / max(Decimal("1e-18"), sum(q for q, _ in lots))),
                realized_quote=realized,
            ))
            continue

        if side == "buy":
            # цена за 1 base
            price = cost / amt
            lots.append((amt, price))

        elif side == "sell":
            qty_to_match = amt
            sell_price = cost / amt  # фактическая цена продажи по чеку (cost/amt)
            while qty_to_match > 0 and lots:
                q, p = lots[0]
                take = q if q <= qty_to_match else qty_to_match
                realized += take * (sell_price - p)
                q_left = q - take
                qty_to_match -= take
                if q_left > 0:
                    lots[0] = (q_left, p)
                else:
                    lots.pop(0)
            # остаток без лотов — считаем как полностью реализованный против нулевой базы (не меняет realized)

        # снимок состояния
        qty = sum(q for q, _ in lots)
        avg = Decimal("0") if qty == 0 else (sum(q * p for q, p in lots) / qty)
        series.append(PnLPoint(qty_base=qty, avg_price=avg, realized_quote=realized))

    return series
