"""
Backtest CLI (long-only, spot):
- гибкая загрузка CSV (timestamp|time|date|datetime, open, high, low, close, volume)
- стратегия EMA cross (как в вашем backtest/strategies/long_only.py)
- движок сделок: купил -> продал (без шортов), учёт комиссии и слиппеджа
- сводка PnL: total, trades, winrate, avg_win/avg_loss, profit_factor
Пример:
    python -m scripts.backtest_cli --csv data/btc_15m.csv --fast 9 --slow 21 --trade-size 100 \
        --fee 0.001 --slip-bps 5 --symbol BTC/USDT
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
import csv
import argparse
from datetime import datetime
@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
_OHLCV_ALIASES = {
    "timestamp": {"timestamp", "time", "ts", "date", "datetime"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c"},
    "volume": {"volume", "vol", "v", "amount"},
}
def _norm_header(cols: Iterable[str]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for name in cols:
        key = (name or "").strip().lower()
        for k, aliases in _OHLCV_ALIASES.items():
            if key in aliases and k not in m:
                m[k] = name
    return m
def _to_ts(v: str) -> int:
    v = (v or "").strip()
    if not v:
        return 0
    try:
        n = int(float(v))
        if n > 2_000_000_000_000:    # точно ms
            return n
        if n < 10_000_000_000:       # секунды
            return n * 1000
        return n
    except Exception:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "").replace("z", ""))
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0
def load_csv(path: str) -> List[Candle]:
    out: List[Candle] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            return out
        hdr = _norm_header(r.fieldnames)
        req = {"timestamp", "open", "high", "low", "close"}
        if not req.issubset(hdr.keys()):
            raise ValueError(f"CSV missing columns: required={sorted(req)}, got={sorted(hdr.keys())}")
        vkey = hdr.get("volume")
        for row in r:
            try:
                ts = _to_ts(str(row[hdr["timestamp"]]))
                o = float(row[hdr["open"]]); h = float(row[hdr["high"]])
                l = float(row[hdr["low"]]);  c = float(row[hdr["close"]])
                v = float(row[vkey]) if vkey and row.get(vkey) not in ("", None) else 0.0
                if ts > 0:
                    out.append(Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v))
            except Exception:
                continue
    out.sort(key=lambda x: x.ts)
    return out
def _ema(prev: float, price: float, period: int) -> float:
    k = 2.0 / (period + 1.0)
    return price * k + prev * (1.0 - k)
@dataclass
class EMACrossLongOnly:
    fast: int = 9
    slow: int = 21
    _ema_fast: Optional[float] = None
    _ema_slow: Optional[float] = None
    _has_long: bool = False
    def on_candle(self, candle: Candle, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        px = float(candle.close)
        self._ema_fast = px if self._ema_fast is None else _ema(self._ema_fast, px, self.fast)
        self._ema_slow = px if self._ema_slow is None else _ema(self._ema_slow, px, self.slow)
        if self._ema_fast is None or self._ema_slow is None:
            return None
        if not self._has_long and self._ema_fast >= self._ema_slow:
            self._has_long = True
            return {"side": "buy"}
        if self._has_long and self._ema_fast < self._ema_slow:
            self._has_long = False
            return {"side": "sell"}
        return None
def realized_pnl_summary(trades: Iterable[Dict[str, Any]], symbol: Optional[str] = None) -> Dict[str, float]:
    """
    Простейшая сводка по реализованной PnL (в quote, напр. USDT).
    Вход: список {'ts','side','price','qty','fee','pnl'} для завершённых сделок (пара buy→sell).
    """
    closed = [t for t in trades if "pnl" in t]
    n = len(closed)
    total = sum(float(t.get("pnl", 0.0)) for t in closed)
    wins = [t for t in closed if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed if float(t.get("pnl", 0.0)) < 0]
    winrate = (len(wins) / n * 100.0) if n else 0.0
    avg_win = sum(float(t["pnl"]) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(abs(float(t["pnl"])) for t in losses) / len(losses) if losses else 0.0
    profit_factor = (sum(float(t["pnl"]) for t in wins) / sum(abs(float(t["pnl"])) for t in losses)) if losses else float("inf")
    return {
        "symbol": symbol or "",
        "trades": float(n),
        "total_pnl": float(total),
        "winrate_pct": float(winrate),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "profit_factor": float(profit_factor),
    }
def backtest(
    candles: List[Candle],
    *,
    fast: int = 9,
    slow: int = 21,
    trade_size: float = 100.0,   # размер покупки в котируемой валюте (например, USDT)
    fee: float = 0.001,          # комиссия (taker) 0.1% = 0.001
    slip_bps: float = 5.0,       # слиппедж в б.п. (5 б.п. = 0.05%)
    symbol: str = "BTC/USDT",
) -> Dict[str, Any]:
    strat = EMACrossLongOnly(fast=fast, slow=slow)
    pos_qty = 0.0
    cash = 0.0         # мы считаем PnL в котируемой валюте; trade_size берём из «кошелька»
    trades: List[Dict[str, Any]] = []
    entry_px = None
    entry_fee = 0.0
    fee_mult_buy = 1.0 + float(fee or 0.0)
    fee_mult_sell = 1.0 - float(fee or 0.0)
    slip_buy = 1.0 + (float(slip_bps) / 10_000.0)
    slip_sell = 1.0 - (float(slip_bps) / 10_000.0)
    for c in candles:
        sig = strat.on_candle(c, {})
        if not sig:
            continue
        if sig["side"] == "buy" and pos_qty == 0.0:
            px = c.close * slip_buy
            qty = (trade_size / px) * fee_mult_sell  # комиссия уменьшит полученную квоту; учтём это в qty
            pos_qty = qty
            entry_px = px
            entry_fee = trade_size * float(fee or 0.0)
            trades.append({"ts": c.ts, "side": "buy", "price": px, "qty": qty, "fee": entry_fee})
            continue
        if sig["side"] == "sell" and pos_qty > 0.0:
            px = c.close * slip_sell
            gross = pos_qty * px
            fee_s = gross * float(fee or 0.0)
            pnl = (gross * fee_mult_sell) - (entry_px * pos_qty) - entry_fee
            trades.append({"ts": c.ts, "side": "sell", "price": px, "qty": pos_qty, "fee": fee_s, "pnl": pnl})
            cash += pnl
            pos_qty = 0.0
            entry_px = None
            entry_fee = 0.0
            continue
    summary = realized_pnl_summary(trades, symbol=symbol)
    return {"symbol": symbol, "trades": trades, "summary": summary}
def main() -> None:
    p = argparse.ArgumentParser(description="Backtest long-only EMA cross (CSV).")
    p.add_argument("--csv", required=True, help="Путь к CSV с колонками (timestamp|time|date|datetime, open, high, low, close[, volume])")
    p.add_argument("--fast", type=int, default=9, help="EMA fast")
    p.add_argument("--slow", type=int, default=21, help="EMA slow")
    p.add_argument("--trade-size", type=float, default=100.0, help="Размер покупки в котируемой валюте (например, 100 USDT)")
    p.add_argument("--fee", type=float, default=0.001, help="Комиссия (taker), 0.001 = 0.1%%")
    p.add_argument("--slip-bps", type=float, default=5.0, help="Слиппедж в б.п. (5 = 0.05%%)")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--out", default="", help="Если указан путь, сохраняет трейды в CSV")
    args = p.parse_args()
    candles = load_csv(args.csv)
    rep = backtest(
        candles,
        fast=args.fast,
        slow=args.slow,
        trade_size=args.trade_size,
        fee=args.fee,
        slip_bps=args.slip_bps,
        symbol=args.symbol,
    )
    s = rep["summary"]
    print(f"Symbol: {rep['symbol']}")
    print(f"Trades: {int(s['trades'])}")
    print(f"Total PnL: {s['total_pnl']:.4f}")
    print(f"Winrate: {s['winrate_pct']:.2f}% | ProfitFactor: {s['profit_factor']:.2f}")
    print(f"Avg Win: {s['avg_win']:.4f} | Avg Loss: {s['avg_loss']:.4f}")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ts", "side", "price", "qty", "fee", "pnl"])
            w.writeheader()
            for t in rep["trades"]:
                w.writerow(t)
if __name__ == "__main__":
    main()
