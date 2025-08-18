# tests/test_telegram_profit_positions.py
import json
import sqlite3
from dataclasses import dataclass

from crypto_ai_bot.app.adapters.telegram import handle_update

@dataclass
class _Bus:
    def health(self): return {"running": True, "dlq_size": 0}

@dataclass
class _PositionsRepo:
    def __init__(self, con): self.con = con
    def get_open(self):
        cur = self.con.execute("SELECT symbol, qty, avg_price FROM positions WHERE qty>0")
        return [{"symbol": s, "qty": float(q), "avg_price": float(a)} for (s,q,a) in cur.fetchall()]

@dataclass
class _TradesRepo:
    def __init__(self, con): self.con = con
    def count_pending(self): return 0

@dataclass
class _Settings:
    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "1h"
    MODE: str = "paper"

@dataclass
class _Container:
    settings: _Settings
    con: sqlite3.Connection
    bus: _Bus
    positions_repo: _PositionsRepo
    trades_repo: _TradesRepo

def _prepare_db():
    con = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    con.execute("""
    CREATE TABLE trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT, side TEXT, price REAL, qty REAL, fee_amt REAL,
      ts INTEGER, state TEXT
    )""")
    con.execute("""
    CREATE TABLE positions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT UNIQUE, qty REAL, avg_price REAL
    )""")
    # имитация покупок и продажи (закрытая часть даёт realized pnl)
    con.execute("INSERT INTO trades(symbol,side,price,qty,fee_amt,ts,state) VALUES(?,?,?,?,?,?,?)",
                ("BTC/USDT","buy",  10000, 0.01, 0.0, 1, "filled"))
    con.execute("INSERT INTO trades(symbol,side,price,qty,fee_amt,ts,state) VALUES(?,?,?,?,?,?,?)",
                ("BTC/USDT","sell", 11000, 0.01, 0.0, 2, "filled"))
    con.execute("INSERT INTO positions(symbol,qty,avg_price) VALUES(?,?,?)",
                ("BTC/USDT", 0.0, 0.0))  # нет открытых
    return con

def _make_container():
    con = _prepare_db()
    return _Container(
        settings=_Settings(),
        con=con,
        bus=_Bus(),
        positions_repo=_PositionsRepo(con),
        trades_repo=_TradesRepo(con),
    )

def _make_update(text: str):
    return json.dumps({"message": {"text": text, "chat": {"id": 123}}}).encode("utf-8")

def test_profit_works_and_normalizes_symbol():
    c = _make_container()
    body = _make_update("/profit btcusdt")
    resp = asyncio_run(handle_update(None, body, c))
    data = json.loads(resp.body.decode("utf-8"))
    assert data["method"] == "sendMessage"
    assert "PnL" in data["text"]

def test_positions_empty_for_symbol():
    c = _make_container()
    body = _make_update("/positions BTCUSDT")
    resp = asyncio_run(handle_update(None, body, c))
    data = json.loads(resp.body.decode("utf-8"))
    assert "нет открытых позиций" in data["text"].lower()

# helper для asyncio, чтобы без pytest-asyncio
def asyncio_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)
