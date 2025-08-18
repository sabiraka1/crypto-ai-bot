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
from crypto_ai_bot.utils import metrics


def main() -> int:
    p = argparse.ArgumentParser(description="Run CSV backtest using current strategy.")
    p.add_argument("csv", help="Path to OHLCV CSV (timestamp,open,high,low,close[,volume])")
    p.add_argument("--symbol", default=None, help="Symbol (default from Settings)")
    p.add_argument("--timeframe", default=None, help="Timeframe label (default from Settings)")
    p.add_argument("--lookback", type=int, default=None, help="Lookback bars fed to strategy (default Settings.LOOKBACK_LIMIT or LIMIT_BARS)")
    p.add_argument("--spread-bps", type=float, default=5.0, help="Synthetic order book spread, bps (default 5)")
    p.add_argument("--slippage-bps", type=float, default=0.0, help="Execution slippage, bps (default 0)")
    p.add_argument("--fee-bps", type=float, default=0.0, help="Per-trade fee, bps (applied via price adjustment)")
    p.add_argument("--fee-fixed", type=float, default=0.0, help="Fixed fee per trade (quote currency), approximated via price adjustment")
    p.add_argument("--db", dest="db_path", default=":memory:", help="SQLite path for run (default :memory:)")
    p.add_argument("--export-trades", dest="export_trades", default=None, help="Write executed trades CSV to path")
    p.add_argument("--out-json", default=None, help="Write full report JSON to file")
    p.add_argument("--out-svg", default=None, help="Write equity curve SVG to file")
    p.add_argument("--metrics-json", default=None, help="Write minimal metrics JSON for server (/metrics)")

    args = p.parse_args()

    cfg = Settings.build()
    cfg.MODE = "backtest"

    rep = run_backtest_from_csv(
        cfg,
        csv_path=args.csv,
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback=args.lookback,
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        fee_bps=args.fee_bps,
        fee_fixed=args.fee_fixed,
        db_path=args.db_path,
        export_trades_path=args.export_trades,
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

    # экспорт «минимальных» метрик для сервера (чтобы /metrics их видел)
    metrics_doc = {
        "backtest_trades_total": rep.trades,
        "backtest_equity_last": (rep.equity_series[-1] if rep.equity_series else 0.0),
        "backtest_max_drawdown_pct": rep.max_drawdown_pct,
    }
    metrics_path = args.metrics_json or getattr(cfg, "BACKTEST_METRICS_PATH", None) or "backtest_metrics.json"
    try:
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics_doc, f, ensure_ascii=False, indent=2)
    except Exception:
        # мягко — отсутствие файла не ломает CLI
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
