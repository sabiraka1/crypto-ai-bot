from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Dict, Any, Tuple

from crypto_ai_bot.utils.decimal import dec


@dataclass
class PnLItem:
    side: str               # "buy" | "sell"
    base_qty: Decimal       # количество в базовой валюте (BTC)
    price: Decimal          # цена (quote/base)
    fee_quote: Decimal      # комиссия в котируемой (USDT)
    ts_ms: Optional[int] = None


@dataclass
class PnLResult:
    realized_quote: Decimal
    remaining_base: Decimal


def _normalize(trades: Iterable[Dict[str, Any]]) -> List[PnLItem]:
    items: List[PnLItem] = []
    for t in trades:
        side = str(t.get("side", "")).lower().strip()
        if side not in ("buy", "sell"):
            continue
        # Поддерживаем разные формы входа:
        #  - base_amount/quote_amount
        #  - amount/price/cost
        #  - filled/price
        base = t.get("base_amount")
        if base is None:
            # amount трактуем как base (для sell) или оцениваем через cost/price (для buy)
            amt = dec(str(t.get("amount", t.get("filled", "0")) or "0"))
            price = dec(str(t.get("price", "0") or "0"))
            cost = dec(str(t.get("cost", "0") or "0"))
            if amt > 0 and price > 0:
                # если это sell — amount обычно base; если buy — amount часто = quote (в некоторых адаптерах)
                if side == "sell":
                    base = amt
                else:
                    # попытка оценить base через cost/price
                    base = cost / price if price > 0 else dec("0")
            else:
                # запасной путь
                if price > 0 and cost > 0:
                    base = cost / price
                else:
                    base = dec("0")
        price = dec(str(t.get("price", "0") or "0"))
        fee_q = dec(str(t.get("fee_quote", "0") or "0"))
        ts = t.get("ts_ms")
        items.append(PnLItem(side=side, base_qty=dec(str(base or 0)),
                             price=price, fee_quote=fee_q, ts_ms=int(ts) if ts else None))
    # сортировка по времени (если есть)
    items.sort(key=lambda x: (x.ts_ms if x.ts_ms is not None else 0))
    return items


def fifo_pnl(trades: Iterable[Dict[str, Any]]) -> PnLResult:
    """
    FIFO-PnL по дневным сделкам: продаём ранее накопленные покупки.
    Возвращает реализованный PnL в котируемой валюте и остаток позиции в базовой.
    """
    items = _normalize(trades)
    # очередь покупок: список (qty, price)
    fifo: List[Tuple[Decimal, Decimal]] = []
    realized = dec("0")
    remaining = dec("0")

    for it in items:
        if it.side == "buy":
            if it.base_qty > 0:
                fifo.append((it.base_qty, it.price))
                remaining += it.base_qty
            realized -= it.fee_quote
        else:  # sell
            qty_to_sell = it.base_qty
            sell_price = it.price
            fee = it.fee_quote
            while qty_to_sell > 0 and fifo:
                buy_qty, buy_price = fifo[0]
                matched = min(qty_to_sell, buy_qty)
                pnl = (sell_price - buy_price) * matched
                realized += pnl
                qty_to_sell -= matched
                buy_qty -= matched
                remaining -= matched
                if buy_qty <= 0:
                    fifo.pop(0)
                else:
                    fifo[0] = (buy_qty, buy_price)
            # если продали больше, чем FIFO-остаток (теоретически не должно быть) — остаток считаем нулём
            realized -= fee

    # нереализованная часть (remaining) нас не интересует в дневном realized
    return PnLResult(realized_quote=realized, remaining_base=remaining)
