# scripts/backtest_cli.py
from __future__ import annotations
import argparse
import os
import sqlite3

from crypto_ai_bot.backtest.dataloader import load_csv
from crypto_ai_bot.backtest.engine import BacktestEngine, BacktestSettings
from crypto_ai_bot.backtest.strategies.long_only import EMACrossLongOnly


def parse_args():
    p = argparse.ArgumentParser(description="Unified backtest runner")
    p.add_argument("--csv", required=True, help="Путь к CSV: timestamp|time,open,high,low,close,volume")
    p.add_argument("--symbol", default=os.environ.get("SYMBOL", "BTC/USDT"))
    p.add_argument("--timeframe", default=os.environ.get("TIMEFRAME", "1h"))
    p.add_argument("--trade-amount", type=float, default=float(os.environ.get("TRADE_AMOUNT", "10")))
    p.add_argument("--fee-taker-bps", type=int, default=int(os.environ.get("FEE_TAKER_BPS", "10")))
    p.add_argument("--slippage-bps", type=int, default=int(os.environ.get("SLIPPAGE_BPS", "5")))
    p.add_argument("--db", default=":memory:", help="SQLite DB для результатов (по умолчанию :memory:)")
    p.add_argument("--ema-fast", type=int, default=9)
    p.add_argument("--ema-slow", type=int, default=21)
    return p.parse_args()


def main():
    args = parse_args()
    con = sqlite3.connect(args.db, isolation_level=None, check_same_thread=False)

    settings = BacktestSettings(
        SYMBOL=args.symbol,
        TIMEFRAME=args.timeframe,
        TRADE_AMOUNT=args.trade_amount,
        FEE_TAKER_BPS=args.fee_taker_bps,
        SLIPPAGE_BPS=args.slippage_bps,
    )

    engine = BacktestEngine(con=con, settings=settings)
    strategy = EMACrossLongOnly(fast=args.ema_fast, slow=args.ema_slow)
    candles = load_csv(args.csv)

    res = engine.run(candles=candles, strategy=strategy)

    summ = res.summary
    print("== Backtest summary ==")
    print(f"symbol: {settings.SYMBOL}  timeframe: {settings.TIMEFRAME}")
    print(f"filled trades: {res.trades}")
    print(f"closed trades: {summ['closed_trades']} (W/L {summ['wins']}/{summ['losses']})")
    print(f"realized PnL: {summ['pnl_abs']:.6f} USDT  ({summ['pnl_pct']:.4f}%)")
    if args.db != ":memory:":
        print(f"results saved to: {args.db}")

if __name__ == "__main__":
    main()
