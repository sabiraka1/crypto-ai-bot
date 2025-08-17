# scripts/backtest_cli.py
from __future__ import annotations
import argparse
import csv
from typing import List, Dict, Any

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository

try:
    from crypto_ai_bot.core.storage.repositories.decisions import SqliteDecisionsRepository
except Exception:
    SqliteDecisionsRepository = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--fee-bps", type=float, default=5.0, help="Комиссия, б.п.")
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Проскальзывание, б.п.")
    args = ap.parse_args()

    class BT(Settings): ...
    cfg = BT.build()
    setattr(cfg, "MODE", "backtest")
    setattr(cfg, "SYMBOL", normalize_symbol(args.symbol))
    setattr(cfg, "TIMEFRAME", normalize_timeframe(args.timeframe))
    setattr(cfg, "LIMIT", int(args.limit))
    # настройки для симулятора (читаются реализацией backtest/paper, если поддерживает)
    setattr(cfg, "FEE_BPS", float(args.fee_bps))
    setattr(cfg, "SLIPPAGE_BPS", float(args.slippage_bps))

    breaker = CircuitBreaker()
    broker = create_broker(mode="backtest", settings=cfg, circuit_breaker=breaker)

    con = connect(getattr(cfg, "DB_PATH", "crypto.db"))
    repos = type("Repos", (), {})()
    repos.positions = SqlitePositionRepository(con)
    repos.trades = SqliteTradeRepository(con)
    repos.audit = SqliteAuditRepository(con)
    repos.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None

    # простой проход по CSV для прогрева, сам broker/backtest должен читать из своих источников;
    # тут нам важен сам цикл eval_and_execute, чтобы проверить логику end-to-end
    with open(args.csv, "r", newline="") as f:
        _ = list(csv.reader(f))  # не используем далее: источник данных — сам broker.backtest

    steps = 0
    for _ in range(int(args.limit)):
        eval_and_execute(cfg, broker, repos, symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT)
        steps += 1

    print(f"Бэктест завершён. Шагов: {steps}, SYMBOL={cfg.SYMBOL}, TF={cfg.TIMEFRAME}, fee={args.fee_bps}bps, slip={args.slippage_bps}bps")


if __name__ == "__main__":
    main()
