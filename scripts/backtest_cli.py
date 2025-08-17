# scripts/backtest_cli.py
from __future__ import annotations
import argparse
import csv
from types import SimpleNamespace
from typing import Dict, Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute

from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
try:
    from crypto_ai_bot.core.storage.repositories.decisions import SqliteDecisionsRepository
except Exception:
    SqliteDecisionsRepository = None
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--fee-bps", type=float, default=5.0, help="Комиссия, б.п.")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Проскальзывание, б.п.")
    args = ap.parse_args()

    class BT(Settings):
        ...

    cfg = BT.build()
    setattr(cfg, "MODE", "backtest")
    setattr(cfg, "SYMBOL", normalize_symbol(args.symbol))
    setattr(cfg, "TIMEFRAME", normalize_timeframe(args.timeframe))
    setattr(cfg, "LIMIT_BARS", int(args.limit))
    # настройки для симулятора (читаются реализацией backtest/paper, если поддерживает)
    setattr(cfg, "FEE_BPS", float(args.fee_bps))
    setattr(cfg, "SLIPPAGE_BPS", float(args.slippage_bps))

    broker = create_broker(cfg)

    con = connect(getattr(cfg, "DB_PATH", "crypto.db"))
    repos = SimpleNamespace(
        positions=SqlitePositionRepository(con),
        trades=SqliteTradeRepository(con),
        audit=SqliteAuditRepository(con),
        uow=SqliteUnitOfWork(con),
        idempotency=SqliteIdempotencyRepository(con),
        decisions=SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None,
    )

    # простой проход по CSV для прогрева, сам broker/backtest читает из своих источников;
    # нам важен сам цикл eval_and_execute, чтобы проверить логику end-to-end
    with open(args.csv, "r", newline="") as f:
        _ = list(csv.reader(f))  # прогрев

    steps = 0
    for _ in range(int(args.limit)):
        eval_and_execute(cfg, broker, repos, symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT_BARS)
        steps += 1

    print(
        f"Бэктест завершён. Шагов: {steps}, SYMBOL={cfg.SYMBOL}, TF={cfg.TIMEFRAME}, fee={args.fee_bps}bps, slip={args.slippage_bps}bps"
    )


if __name__ == "__main__":
    main()
