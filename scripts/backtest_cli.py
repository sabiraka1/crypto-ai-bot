# scripts/backtest_cli.py
import argparse
from crypto_ai_bot.backtest.runner import run_backtest

def main():
    ap = argparse.ArgumentParser(description="Unified Backtest CLI")
    ap.add_argument("--csv", required=True, help="Path to OHLCV CSV: ts,open,high,low,close,volume")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--starting-cash", type=float, default=1000.0)
    ap.add_argument("--trade-amount", type=float, default=10.0)
    ap.add_argument("--fee-taker-bps", type=float, default=10.0, help="Taker fee in bps (0.10% = 10)")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage in bps")
    args = ap.parse_args()

    res = run_backtest(
        args.csv,
        symbol=args.symbol,
        starting_cash=args.starting_cash,
        trade_amount=args.trade_amount,
        fee_taker_bps=args.fee_taker_bps,
        slippage_bps=args.slippage_bps
    )
    print("Backtest result:")
    for k, v in res.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
