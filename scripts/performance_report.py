#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.logging import get_logger

log = get_logger("perf_report")

# Допускаем разные схемы таблицы trades: берём минимально необходимое — ts_ms, side, amount(base), price, cost, fee
# Если price/cost/fee отсутствуют — пытаемся восстановить по имеющимся полям; если нельзя — пропускаем метрику.

@dataclass
class Trade:
    ts_ms: int
    side: str  # 'buy' | 'sell'
    amount: Decimal  # base amount
    price: Optional[Decimal]  # quote/base
    cost: Optional[Decimal]   # quote (после/до комиссии — как есть)
    fee: Optional[Decimal]    # quote


def _load_trades(conn: sqlite3.Connection, *, symbol: Optional[str], since_ms: Optional[int], until_ms: Optional[int]) -> List[Trade]:
    cols = ["ts_ms", "side", "amount", "price", "cost", "fee", "symbol"]
    have_symbol = False
    # проверяем наличие колонок
    cur = conn.execute("PRAGMA table_info(trades)")
    fields = {r[1] for r in cur.fetchall()}
    required = {"ts_ms", "side", "amount"}
    if not required.issubset(fields):
        raise RuntimeError("trades table must contain ts_ms, side, amount")
    have_price = "price" in fields
    have_cost = "cost" in fields
    have_fee = "fee" in fields
    have_symbol = "symbol" in fields

    q = "SELECT ts_ms, side, amount" + (", price" if have_price else "") + (", cost" if have_cost else "") + (", fee" if have_fee else "")
    if have_symbol:
        q += ", symbol"
    q += " FROM trades WHERE 1=1"
    args: List[Any] = []
    if symbol and have_symbol:
        q += " AND symbol = ?"
        args.append(symbol)
    if since_ms is not None:
        q += " AND ts_ms >= ?"
        args.append(int(since_ms))
    if until_ms is not None:
        q += " AND ts_ms <= ?"
        args.append(int(until_ms))
    q += " ORDER BY ts_ms ASC"

    res: List[Trade] = []
    for row in conn.execute(q, args):
        ts_ms, side, amount, *rest = row
        price = cost = fee = None
        idx = 0
        if have_price:
            price = Decimal(str(rest[idx] if rest[idx] is not None else 0)); idx += 1
        if have_cost:
            v = rest[idx]; idx += 1
            cost = Decimal(str(v if v is not None else 0))
        if have_fee:
            v = rest[idx]; idx += 1
            fee = Decimal(str(v if v is not None else 0))
        # symbol at the end ignored for now
        res.append(Trade(int(ts_ms), str(side), Decimal(str(amount)), price, cost, fee))
    return res


def _fifo_realized_pnl(trades: List[Trade]) -> Tuple[Decimal, int, int, List[Tuple[int, Decimal]]]:
    """
    FIFO по сделкам: усредняем входы (BUY) и списываем при выходах (SELL).
    Возвращаем: (realized_pnl_quote, wins, losses, equity_nodes)
    equity_nodes: [(ts_ms, equity_quote)] по точкам сделок (без марк‑ту‑маркет между ними).
    """
    inventory = Decimal("0")  # base
    cash = Decimal("0")       # quote
    lots = deque()  # (amount_base, price_quote)
    wins = losses = 0
    equity_nodes: List[Tuple[int, Decimal]] = []

    for t in trades:
        if t.side == "buy":
            price = t.price if (t.price is not None) else (t.cost / t.amount if (t.cost and t.amount) else None)
            if price is None:
                # невозможно оценить — пропускаем влияние на PnL, но учитываем инвентарь
                price = Decimal("0")
            lots.append((t.amount, price))
            inventory += t.amount
            # денежный поток: тратим cost, если нет — берем amount*price
            outflow = t.cost if t.cost is not None else (t.amount * price)
            cash -= (outflow or Decimal("0"))
        elif t.side == "sell":
            price = t.price if (t.price is not None) else (t.cost / t.amount if (t.cost and t.amount) else None)
            if price is None:
                price = Decimal("0")
            qty = t.amount
            realized = Decimal("0")
            # закрываем FIFO‑лоты
            while qty > 0 and lots:
                lot_qty, lot_price = lots[0]
                take = min(qty, lot_qty)
                realized += take * (price - lot_price)
                lot_qty -= take
                qty -= take
                if lot_qty == 0:
                    lots.popleft()
                else:
                    lots[0] = (lot_qty, lot_price)
            # денежный поток: получаем cost (или amount*price)
            inflow = t.cost if t.cost is not None else (t.amount * price)
            cash += (inflow or Decimal("0"))
            if realized > 0:
                wins += 1
            elif realized < 0:
                losses += 1
        equity_nodes.append((t.ts_ms, cash))
    # Реализованный PnL — это cash при inventory=0; если inventory != 0 — это PnL закрытых сделок
    realized = cash
    return realized, wins, losses, equity_nodes


def _max_drawdown(series: List[Tuple[int, Decimal]]) -> Tuple[Decimal, Optional[Tuple[int, int]]]:
    peak = Decimal("-Infinity")
    max_dd = Decimal("0")
    max_window: Optional[Tuple[int, int]] = None
    for ts, val in series:
        if val > peak:
            peak = val
            start_ts = ts
        dd = (peak - val)
        if dd > max_dd:
            max_dd = dd
            max_window = (start_ts, ts)
    return max_dd, max_window


def generate_report(db_path: str, *, symbol: Optional[str], since: Optional[str], until: Optional[str], end_price: Optional[float]) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        since_ms = int(datetime.fromisoformat(since).timestamp() * 1000) if since else None
        until_ms = int(datetime.fromisoformat(until).timestamp() * 1000) if until else None
        trades = _load_trades(conn, symbol=symbol, since_ms=since_ms, until_ms=until_ms)
        realized, wins, losses, equity_nodes = _fifo_realized_pnl(trades)

        total_trades = len(trades)
        closed_trades = wins + losses
        winrate = (wins / closed_trades * 100.0) if closed_trades > 0 else 0.0
        max_dd, dd_window = _max_drawdown(equity_nodes)

        # Марк‑ту‑маркет на конец периода (если передан end_price и есть инвентарь)
        inv_base = Decimal("0")
        for t in trades:
            if t.side == "buy":
                inv_base += t.amount
            else:
                inv_base -= t.amount
        mtm = None
        if end_price is not None:
            mtm = inv_base * Decimal(str(end_price))

        summary = {
            "total_trades": total_trades,
            "closed_trades": closed_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(winrate, 2),
            "realized_pnl_quote": float(realized),
            "max_drawdown_quote": float(max_dd),
            "drawdown_window": dd_window,
            "inventory_base": float(inv_base),
            "mtm_quote": float(mtm) if mtm is not None else None,
        }
        return {"summary": summary, "equity_nodes": equity_nodes[:1000]}  # ограничим вывод
    finally:
        conn.close()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Performance report (FIFO PnL, win-rate, equity curve)")
    ap.add_argument("--db", default=None, help="Path to sqlite db (default: Settings.DB_PATH)")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--since", default=None, help="ISO date, e.g. 2025-01-01T00:00:00")
    ap.add_argument("--until", default=None, help="ISO date")
    ap.add_argument("--end-price", type=float, default=None, help="Mark-to-market price for remaining inventory")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    args = ap.parse_args(argv)

    s = Settings.load()
    db = args.db or s.DB_PATH

    rep = generate_report(db, symbol=args.symbol, since=args.since, until=args.until, end_price=args.end_price)

    if args.format == "json":
        print(json.dumps(rep, indent=2, default=str, ensure_ascii=False))
    else:
        sm = rep["summary"]
        print("\nPERFORMANCE SUMMARY")
        print("-------------------")
        for k in ("total_trades", "closed_trades", "wins", "losses", "win_rate_pct",
                  "realized_pnl_quote", "max_drawdown_quote", "inventory_base", "mtm_quote"):
            print(f"{k}: {sm.get(k)}")
        print("\n(first 10 equity nodes)")
        for ts, val in rep["equity_nodes"][:10]:
            print(datetime.utcfromtimestamp(ts/1000.0).isoformat(), float(val))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())