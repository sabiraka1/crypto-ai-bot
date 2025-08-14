
# -*- coding: utf-8 -*-
"""
crypto_ai_bot.core.storage.sqlite_adapter
----------------------------------------
Р›С‘РіРєР°СЏ СЂРµР°Р»РёР·Р°С†РёСЏ СЂРµРїРѕР·РёС‚РѕСЂРёРµРІ РЅР° SQLite (Phase 5).
- РђРІС‚Рѕ-СЃРѕР·РґР°РЅРёРµ СЃС…РµРјС‹ (РµСЃР»Рё Р‘Р” РЅРµ СЃСѓС‰РµСЃС‚РІСѓРµС‚)
- РџСЂРѕСЃС‚С‹Рµ CRUD-РѕРїРµСЂР°С†РёРё РґР»СЏ trades/positions/snapshots
- РџСѓС‚СЊ Рє Р‘Р”: join(Settings.DATA_DIR, 'bot.sqlite3')

РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ:
    from crypto_ai_bot.core.settings import Settings
    from crypto_ai_bot.core.storage.sqlite_adapter import SQLiteStorage

    cfg = Settings.build()
    storage = SQLiteStorage.from_settings(cfg)
    storage.ensure_schema()

    trades = storage.trades
    trades.add_trade(...)
"""
from __future__ import annotations

import os
import json
import sqlite3
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from crypto_ai_bot.core.settings import Settings


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL DEFAULT 0.0,
    ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_price REAL NOT NULL,
    status TEXT NOT NULL,         -- open/closed
    opened_ts INTEGER NOT NULL,
    closed_ts INTEGER,
    pnl REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pos_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT DEFAULT 'market',
    qty REAL NOT NULL,
    price REAL,
    status TEXT DEFAULT 'filled',
    ts INTEGER NOT NULL,
    FOREIGN KEY (pos_id) REFERENCES positions(id)
);

CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_orders_pos ON orders(pos_id);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_ts ON snapshots(symbol, ts);
"""


def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)


@dataclass
class Trade:
    symbol: str
    side: str     # buy/sell
    qty: float
    price: float
    fee: float = 0.0
    ts: int = 0


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float
    status: str = "open"    # open/closed
    opened_ts: int = 0
    closed_ts: Optional[int] = None
    pnl: float = 0.0


class SQLiteTradeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add_trade(self, t: Trade) -> int:
        if not t.ts:
            t.ts = _now_ms()
        cur = self.conn.execute(
            "INSERT INTO trades(symbol, side, qty, price, fee, ts) VALUES(?,?,?,?,?,?)",
            (t.symbol, t.side, float(t.qty), float(t.price), float(t.fee), int(t.ts)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT id, symbol, side, qty, price, fee, ts FROM trades ORDER BY ts DESC LIMIT ?",
            (int(limit),)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def realized_pnl(self, symbol: Optional[str] = None) -> float:
        # РџСЂРѕСЃС‚РµР№С€Р°СЏ РѕС†РµРЅРєР°: СЃСѓРјРјР° (side=='sell' ? +(price*qty) : -(price*qty)) - fee
        q = "SELECT side, qty, price, fee FROM trades"
        args: Tuple[Any, ...] = ()
        if symbol:
            q += " WHERE symbol=?"
            args = (symbol,)
        pnl = 0.0
        for side, qty, price, fee in self.conn.execute(q, args):
            sign = +1.0 if side.lower() == "sell" else -1.0
            pnl += sign * float(qty) * float(price) - float(fee)
        return float(pnl)


class SQLitePositionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def open_position(self, p: Position) -> int:
        if not p.opened_ts:
            p.opened_ts = _now_ms()
        cur = self.conn.execute(
            "INSERT INTO positions(symbol, qty, avg_price, status, opened_ts, closed_ts, pnl) VALUES(?,?,?,?,?,?,?)",
            (p.symbol, float(p.qty), float(p.avg_price), p.status, int(p.opened_ts), p.closed_ts, float(p.pnl)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_open(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if symbol:
            cur = self.conn.execute(
                "SELECT * FROM positions WHERE status='open' AND symbol=? ORDER BY opened_ts DESC", (symbol,)
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY opened_ts DESC"
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def close_position(self, pos_id: int, close_price: float) -> None:
        # РїСЂРѕСЃС‚Р°СЏ РјРѕРґРµР»СЊ: PnL = (close_price - avg_price)*qty
        cur = self.conn.execute("SELECT qty, avg_price FROM positions WHERE id=? AND status='open'", (pos_id,))
        row = cur.fetchone()
        if not row:
            return
        qty, avg_price = float(row[0]), float(row[1])
        pnl = (float(close_price) - avg_price) * qty
        self.conn.execute(
            "UPDATE positions SET status='closed', closed_ts=?, pnl=? WHERE id=?",
            (_now_ms(), float(pnl), int(pos_id))
        )
        self.conn.commit()


class SQLiteSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add_snapshot(self, ts_ms: int, symbol: str, timeframe: str, payload: Dict[str, Any]) -> int:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cur = self.conn.execute(
            "INSERT INTO snapshots(ts, symbol, timeframe, payload) VALUES(?,?,?,?)",
            (int(ts_ms), symbol, timeframe, data)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_recent(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if symbol:
            cur = self.conn.execute(
                "SELECT id, ts, symbol, timeframe, payload FROM snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?",
                (symbol, int(limit))
            )
        else:
            cur = self.conn.execute(
                "SELECT id, ts, symbol, timeframe, payload FROM snapshots ORDER BY ts DESC LIMIT ?",
                (int(limit),)
            )
        cols = [d[0] for d in cur.description]
        out: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            try:
                d["payload"] = json.loads(d["payload"])
            except Exception:
                pass
            out.append(d)
        return out


class SQLiteStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.trades = SQLiteTradeRepository(self.conn)
        self.positions = SQLitePositionRepository(self.conn)
        self.snapshots = SQLiteSnapshotRepository(self.conn)

    @classmethod
    def from_settings(cls, cfg: Settings) -> "SQLiteStorage":
        data_dir = cfg.DATA_DIR or "data"
        os.makedirs(data_dir, exist_ok=True)
        return cls(os.path.join(data_dir, "bot.sqlite3"))

    def ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

