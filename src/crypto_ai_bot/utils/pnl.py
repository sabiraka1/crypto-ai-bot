from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec


@dataclass
class PnLItem:
    side: str  # "buy" | "sell"
    base_qty: Decimal  # ДћВєДћВѕДћВ»ДћВёГ‘вЂЎДћВµГ‘ВЃГ‘вЂљДћВІДћВѕ ДћВІ ДћВ±ДћВ°ДћВ·ДћВѕДћВІДћВѕДћВ№ ДћВІДћВ°ДћВ»Г‘ВЋГ‘вЂљДћВµ
    price: Decimal  # Г‘вЂ ДћВµДћВЅДћВ° (quote/base)
    fee_quote: Decimal  # ДћВєДћВѕДћВјДћВёГ‘ВЃГ‘ВЃДћВёГ‘ВЏ ДћВІ ДћВєДћВѕГ‘вЂљДћВёГ‘в‚¬Г‘Ж’ДћВµДћВјДћВѕДћВ№ ДћВІДћВ°ДћВ»Г‘ВЋГ‘вЂљДћВµ
    ts_ms: int | None = None


@dataclass
class PnLResult:
    realized_quote: Decimal
    remaining_base: Decimal


def _normalize(trades: Iterable[dict[str, Any]]) -> list[PnLItem]:
    items: list[PnLItem] = []
    for t in trades:
        side = str(t.get("side", "")).lower().strip()
        if side not in ("buy", "sell"):
            continue
        base = t.get("base_amount")
        if base is None:
            amt = dec(str(t.get("amount", t.get("filled", "0")) or "0"))
            price = dec(str(t.get("price", "0") or "0"))
            cost = dec(str(t.get("cost", "0") or "0"))
            if amt > 0 and price > 0:
                if side == "sell":
                    base = amt
                else:
                    base = cost / price if price > 0 else dec("0")
            else:
                base = cost / price if (price > 0 and cost > 0) else dec("0")
        price = dec(str(t.get("price", "0") or "0"))
        fee_q = dec(str(t.get("fee_quote", "0") or "0"))
        ts = t.get("ts_ms")
        items.append(
            PnLItem(
                side=side,
                base_qty=dec(str(base or 0)),
                price=price,
                fee_quote=fee_q,
                ts_ms=int(ts) if ts else None,
            )
        )
    items.sort(key=lambda x: (x.ts_ms if x.ts_ms is not None else 0))
    return items


def fifo_pnl(trades: Iterable[dict[str, Any]]) -> PnLResult:
    items = _normalize(trades)
    fifo: list[tuple[Decimal, Decimal]] = []
    realized = dec("0")
    remaining = dec("0")

    for it in items:
        if it.side == "buy":
            if it.base_qty > 0:
                fifo.append((it.base_qty, it.price))
                remaining += it.base_qty
            realized -= it.fee_quote
        else:
            qty_to_sell = it.base_qty
            sell_price = it.price
            realized -= it.fee_quote
            while qty_to_sell > 0 and fifo:
                buy_qty, buy_price = fifo[0]
                matched = min(qty_to_sell, buy_qty)
                realized += (sell_price - buy_price) * matched
                qty_to_sell -= matched
                buy_qty -= matched
                remaining -= matched
                if buy_qty <= 0:
                    fifo.pop(0)
                else:
                    fifo[0] = (buy_qty, buy_price)

    return PnLResult(realized_quote=realized, remaining_base=remaining)


# Backward-compatible alias expected by some callers/tests
calculate_fifo_pnl = fifo_pnl
