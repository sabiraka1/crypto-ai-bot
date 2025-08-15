
# -*- coding: utf-8 -*-
"""
CSV -> SQLite migration (one-off helper).
Looks for CSV files from Settings (closed_trades.csv, signals_snapshots.csv)
and imports them into SQLite tables (trades, snapshots).
"""
from __future__ import annotations

import os
import csv
import json
import time

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.storage.sqlite_adapter import SqliteDB, SqliteTradeRepo, SqliteSnapshotRepo, get_default_db_path
from crypto_ai_bot.core.storage.repositories.trades import Trade
from crypto_ai_bot.core.storage.repositories.snapshots import Snapshot


def run_migration():
    cfg = Settings.build()
    db_path = get_default_db_path(cfg)
    db = SqliteDB(db_path)
    trades = SqliteTradeRepo(db)
    snaps = SqliteSnapshotRepo(db)

    # Closed trades CSV
    ct_path = cfg.CLOSED_TRADES_CSV
    if ct_path and os.path.exists(ct_path):
        with open(ct_path, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                try:
                    t = Trade(
                        id=r.get("id") or str(int(time.time()*1000)),
                        pos_id=r.get("pos_id") or None,
                        symbol=r.get("symbol") or cfg.SYMBOL,
                        side=r.get("side") or "buy",
                        qty=float(r.get("qty") or r.get("amount") or 0.0),
                        price=float(r.get("price") or 0.0),
                        fee=float(r.get("fee") or 0.0),
                        ts=int(r.get("ts") or r.get("timestamp") or int(time.time()*1000))
                    )
                    trades.add(t)
                except Exception:
                    pass

    # Signals snapshots CSV
    ss_path = cfg.SIGNALS_CSV
    if ss_path and os.path.exists(ss_path):
        with open(ss_path, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                try:
                    ts = int(r.get("ts") or r.get("timestamp") or int(time.time()*1000))
                    symbol = r.get("symbol") or cfg.SYMBOL
                    tf = r.get("timeframe") or cfg.TIMEFRAME
                    data = json.loads(r.get("data") or "{}")
                    snaps.save(Snapshot(ts=ts, symbol=symbol, timeframe=tf, data=data))
                except Exception:
                    pass


if __name__ == "__main__":
    run_migration()
    print("Migration completed.")









