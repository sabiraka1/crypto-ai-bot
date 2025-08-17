# scripts/backtest_cli.py
"""
Простой CLI для локального бэктеста на CSV.
Пример:
  PYTHONPATH=src python scripts/backtest_cli.py --csv data/BTCUSDT-1h.csv --symbol BTC/USDT --timeframe 1h --limit 500
"""

from __future__ import annotations
import argparse
import csv
from decimal import Decimal
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
    args = ap.parse_args()

    # Настройки в режиме backtest
    class BT(Settings): ...
    cfg = BT.build()
    setattr(cfg, "MODE", "backtest")
    setattr(cfg, "SYMBOL", args.symbol)
    setattr(cfg, "TIMEFRAME", args.timeframe)
    setattr(cfg, "LIMIT", args.limit)

    # Брокер (backtest)
    breaker = CircuitBreaker()
    broker = create_broker(mode="backtest", settings=cfg, circuit_breaker=breaker)

    # Хранилище (SQLite)
    con = connect(getattr(cfg, "DB_PATH", "crypto.db"))
    repos = type("Repos", (), {})()
    repos.positions = SqlitePositionRepository(con)
    repos.trades = SqliteTradeRepository(con)
    repos.audit = SqliteAuditRepository(con)
    repos.decisions = SqliteDecisionsRepository(con) if SqliteDecisionsRepository else None

    # Грубый реплей: читаем CSV и по каждому шагу запускаем eval_and_execute.
    # Ожидаемый CSV: time,open,high,low,close,volume
    # Реальный backtest_exchange у тебя уже есть/будет — это просто минимальный CLI для отладки.
    with open(args.csv, "r", newline="") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)

    # Для простоты — ограничимся N последними барами
    rows = rows[-args.limit:]

    decisions = 0
    for i in range(len(rows)):
        res = eval_and_execute(cfg, broker, repos, symbol=args.symbol, timeframe=args.timeframe, limit=min(i + 1, args.limit))
        decisions += 1

    print(f"Бэктест завершён. Пройдено шагов: {decisions}")


if __name__ == "__main__":
    main()
