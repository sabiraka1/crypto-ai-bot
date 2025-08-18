#!/usr/bin/env python3
# scripts/backtest_csv.py
from __future__ import annotations

import argparse
import json
import os
from typing import Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.backtest.runner import run_backtest_from_csv
from crypto_ai_bot.utils.charts import render_profit_curve_svg


def main() -> int:
    p = argparse.ArgumentParser(description="Run CSV backtest using current strategy.")
    p.add_argument("csv", help="Path to OHLCV CSV (timestamp,open,high,low,close[,volume])")
    p.add_argument("--symbol", default=None, help="Symbol (default from Settings)")
    p.add_argument("--timeframe", default=None, help="Timeframe label (default from Settings)")
    p.add_argument("--lookback", type=int, default=None, help="Lookback bars fed to strategy (default Settings.LOOKBACK_LIMIT or LIMIT_BARS)")
    p.add_argument("--spread-bps", type=float, default=5.0, help="Synthetic spread in basis points (default 5)")
    p.add_argument("--db", dest="db_path", default=":memory:", help="SQLite path for run (default :memory:)")
    p.add_argument("--out-json", default=None, help="Write report JSON to file")
    p.add_argument("--out-svg", default=None, help="Write equity curve SVG to file")
    args = p.parse_args()

    cfg = Settings.build()
    # В режиме бэктеста безопаснее выключить торговлю, если вдруг где-то проверяется
    cfg.MODE = "backtest"

    rep = run_backtest_from_csv(
        cfg,
        csv_path=args.csv,
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback=args.lookback,
        spread_bps=args.spread_bps,
        db_path=args.db_path,
    )

    payload = {
        "symbol": rep.symbol,
        "timeframe": rep.timeframe,
        "bars": rep.bars,
        "trades": rep.trades,
        "total_pnl": rep.total_pnl,
        "max_drawdown_pct": rep.max_drawdown_pct,
        "win_rate_pct": rep.win_rate_pct,
        "meta": rep.meta,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump({**payload, "equity_series": rep.equity_series, "closed_pnls": rep.closed_pnls},
                      f, ensure_ascii=False, indent=2)

    if args.out_svg:
        svg = render_profit_curve_svg(rep.closed_pnls, title=f"{rep.symbol} equity")
        with open(args.out_svg, "wb") as f:
            f.write(svg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
