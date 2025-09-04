from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec


@dataclass
class PnLItem:
    side: str  # "buy" | "sell"
    base_qty: Decimal  # количество в базовой валюте (BASE)
    price: Decimal  # цена (QUOTE/BASE)
    fee_quote: Decimal  # комиссия в котируемой валюте (QUOTE)
    ts_ms: int | None = None
    _seq: int = 0  # внутренний счётчик для стабильной сортировки


@dataclass
class PnLResult:
    realized_quote: Decimal
    remaining_base: Decimal


def _extract_fee_quote(t: dict[str, Any]) -> Decimal:
    """
    Возвращаем комиссию в котируемой валюте (quote):
      - приоритет: fee_quote
      - затем fee={"cost": ...}
      - затем fees=[{"cost": ...}, ...] (сумма)
    Если формат неизвестен — считаем 0.
    """
    # 1) прямое поле
    fq = t.get("fee_quote")
    if fq is not None:
        return dec(str(fq))

    # 2) единичный fee-объект
    fee = t.get("fee")
    if isinstance(fee, dict) and "cost" in fee:
        # предполагаем, что указано в quote; если нет — корректируй на уровне адаптера брокера
        return dec(str(fee.get("cost")))

    # 3) список комиссий
    fees = t.get("fees")
    if isinstance(fees, list):
        total = dec("0")
        for f in fees:
            if isinstance(f, dict) and "cost" in f:
                total += dec(str(f.get("cost")))
        return total

    return dec("0")


def _base_qty_from_trade(t: dict[str, Any], side: str, price: Decimal) -> Decimal:
    """
    Аккуратно определяем количество в базовой валюте:
      base_amount -> amount -> filled -> cost/price -> 0
    """
    # 1) явная база
    if t.get("base_amount") is not None:
        return dec(str(t["base_amount"]))

    # 2) amount/filled в CCXT, как правило, уже в базовой валюте
    for k in ("amount", "filled"):
        if t.get(k) is not None:
            q = dec(str(t.get(k)))
            if q > 0:
                return q

    # 3) извлекаем из cost/price (если есть)
    cost = dec(str(t.get("cost", "0") or "0"))
    if cost > 0 and price > 0:
        return cost / price

    return dec("0")


def _normalize(trades: Iterable[dict[str, Any]]) -> list[PnLItem]:
    items: list[PnLItem] = []
    for i, t in enumerate(trades):
        side = str(t.get("side", "")).lower().strip()
        if side not in ("buy", "sell"):
            continue

        price = dec(str(t.get("price", "0") or "0"))
        fee_q = _extract_fee_quote(t)
        ts = t.get("ts_ms")
        ts_ms = int(ts) if ts is not None else None

        base = _base_qty_from_trade(t, side, price)

        items.append(
            PnLItem(
                side=side,
                base_qty=base,
                price=price,
                fee_quote=fee_q,
                ts_ms=ts_ms,
                _seq=i,  # исходный порядок для стабильной сортировки
            )
        )

    # Стабильный порядок: по времени, затем по входной позиции
    items.sort(key=lambda x: (x.ts_ms if x.ts_ms is not None else x._seq, x._seq))
    return items


def fifo_pnl(trades: Iterable[dict[str, Any]]) -> PnLResult:
    """
    Рассчитать реализованный PnL по FIFO и остаток базовой валюты.
    Принципы:
      - Покупки формируют лоты FIFO. Комиссия buy капитализируется в цене лота:
        effective_buy_price = price + fee_quote/base_qty.
      - Продажи списывают лоты FIFO. Комиссия sell вычитается из realized.
    Возвращает:
      realized_quote — реализованный PnL в котируемой валюте,
      remaining_base — остаток базовой валюты (сумма лотов).
    """
    items = _normalize(trades)

    # FIFO-очередь лотов: [(qty_base, effective_buy_price_quote_per_base)]
    fifo: list[tuple[Decimal, Decimal]] = []
    realized = dec("0")

    for it in items:
        if it.base_qty <= 0:
            # пустые/битые записи пропускаем
            continue

        if it.side == "buy":
            # включаем комиссию в стоимость лота (если есть база)
            eff_price = it.price
            if it.fee_quote > 0 and it.base_qty > 0:
                eff_price = eff_price + (it.fee_quote / it.base_qty)
            fifo.append((it.base_qty, eff_price))
        else:
            # комиссия продажи списывается из realized сразу
            if it.fee_quote > 0:
                realized -= it.fee_quote

            qty_to_sell = it.base_qty
            sell_price = it.price

            # списываем покупки FIFO
            while qty_to_sell > 0 and fifo:
                buy_qty, buy_price_eff = fifo[0]
                matched = min(qty_to_sell, buy_qty)

                # PnL = (цена продажи - эффективная цена покупки) * матчинговый объём
                realized += (sell_price - buy_price_eff) * matched

                qty_to_sell -= matched
                buy_qty -= matched

                if buy_qty <= 0:
                    fifo.pop(0)
                else:
                    fifo[0] = (buy_qty, buy_price_eff)

            # Если qty_to_sell > 0, значит «короткая» попытка. Логики short здесь нет — остаток игнорируем.

    remaining = sum((q for q, _ in fifo), dec("0"))
    return PnLResult(realized_quote=realized, remaining_base=remaining)


# Расширенный отчёт по FIFO (не ломает обратную совместимость основного API)
def fifo_detail(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """
    Возвращает подробности:
      - realized_quote
      - remaining_base
      - remaining_cost_quote (стоимость остатка по эффективным ценам покупки)
      - lots: список лотов (qty_base, effective_buy_price)
      - avg_entry_price (для остатка; 0 если позиция чистая)
    """
    items = _normalize(trades)

    fifo: list[tuple[Decimal, Decimal]] = []
    realized = dec("0")

    for it in items:
        if it.base_qty <= 0:
            continue
        if it.side == "buy":
            eff_price = it.price
            if it.fee_quote > 0 and it.base_qty > 0:
                eff_price = eff_price + (it.fee_quote / it.base_qty)
            fifo.append((it.base_qty, eff_price))
        else:
            if it.fee_quote > 0:
                realized -= it.fee_quote
            qty_to_sell = it.base_qty
            sell_price = it.price
            while qty_to_sell > 0 and fifo:
                buy_qty, buy_price_eff = fifo[0]
                matched = min(qty_to_sell, buy_qty)
                realized += (sell_price - buy_price_eff) * matched
                qty_to_sell -= matched
                buy_qty -= matched
                if buy_qty <= 0:
                    fifo.pop(0)
                else:
                    fifo[0] = (buy_qty, buy_price_eff)

    remaining = sum((q for q, _ in fifo), dec("0"))
    remaining_cost = sum((q * p for q, p in fifo), dec("0"))
    avg_entry = (remaining_cost / remaining) if remaining > 0 else dec("0")

    return {
        "realized_quote": realized,
        "remaining_base": remaining,
        "remaining_cost_quote": remaining_cost,
        "lots": fifo,
        "avg_entry_price": avg_entry,
    }


# Backward-compatible alias expected by some callers/tests
calculate_fifo_pnl = fifo_pnl
