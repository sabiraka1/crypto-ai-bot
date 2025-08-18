# scripts/backtest_cli.py
import argparse, csv, tempfile, os, random, time
from crypto_ai_bot.backtest.runner import run_backtest

def _make_demo_series(bars=600, tf_min=15, start_price=30000.0):
    rows = []
    ts = int(time.time() * 1000) - bars * tf_min * 60_000
    px = start_price
    for _ in range(bars):
        drift = random.uniform(-0.002, 0.002)  # ±0.2%
        px = max(100.0, px * (1.0 + drift))
        high = px * (1 + random.uniform(0, 0.001))
        low  = px * (1 - random.uniform(0, 0.001))
        open_ = (high + low) / 2
        close = px
        vol = random.uniform(10, 200)
        rows.append([ts, round(open_, 2), round(high, 2), round(low, 2), round(close, 2), round(vol, 4)])
        ts += tf_min * 60_000
    return rows

def _write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description="Unified Backtest CLI")
    ap.add_argument("--csv", help="Path to OHLCV CSV: ts,open,high,low,close,volume")
    ap.add_argument("--demo", action="store_true", help="Generate synthetic OHLCV instead of CSV file")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--starting-cash", type=float, default=1000.0)
    ap.add_argument("--trade-amount", type=float, default=10.0)
    ap.add_argument("--fee-taker-bps", type=float, default=10.0, help="Taker fee in bps (0.10% = 10)")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage in bps")
    ap.add_argument("--trades-out", help="Path to write trades CSV")
    ap.add_argument("--equity-out", help="Path to write equity curve CSV")
    args = ap.parse_args()

    if not args.demo and not args.csv:
        ap.error("provide --csv or --demo")

    csv_path = args.csv
    tmp_path = None
    if args.demo:
        rows = _make_demo_series(bars=600, tf_min=15, start_price=30000.0)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        tmp_path = tmp.name
        tmp.close()
        _write_csv(tmp_path, ["ts","open","high","low","close","volume"], rows)
        csv_path = tmp_path

    res = run_backtest(
        csv_path,
        symbol=args.symbol,
        starting_cash=args.starting_cash,
        trade_amount=args.trade_amount,
        fee_taker_bps=args.fee_taker_bps,
        slippage_bps=args.slippage_bps,
        collect_trades=bool(args.trades_out),
        collect_equity=bool(args.equity_out),
    )

    print("Backtest result:")
    for k in ("trades","wins","losses","win_rate","final_equity","pnl","max_drawdown"):
        print(f"{k}: {res[k]}")

    # Экспорт, если нужно
    if args.trades_out and "trades_list" in res:
        _write_csv(args.trades_out, ["ts","side","price","qty","fee","pnl"],
                   [[t.get("ts"), t.get("side"), t.get("price"), t.get("qty"), t.get("fee"), t.get("pnl")] for t in res["trades_list"]])
        print(f"trades -> {args.trades_out}")
    if args.equity_out and "equity_curve" in res:
        _write_csv(args.equity_out, ["ts","equity"],
                   [[p["ts"], p["equity"]] for p in res["equity_curve"]])
        print(f"equity -> {args.equity_out}")

    if tmp_path:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

if __name__ == "__main__":
    main()
