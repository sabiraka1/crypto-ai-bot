# src/crypto_ai_bot/backtest/engine.py
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple, List

from crypto_ai_bot.core.storage.migrations.runner import apply_all
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository  # noqa: F401
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.use_cases.evaluate import eval_and_execute


# -------- Settings wrapper (paper-mode) --------

@dataclass
class BacktestSettings:
    SYMBOL: str = "BTC/USDT"
    MODE: str = "paper"                  # важное: place_order перейдёт в paper-ветку
    ENABLE_TRADING: bool = False         # и не будет вызывать broker.create_order
    TRADE_AMOUNT: float = 10.0
    FEE_TAKER_BPS: int = 10
    SLIPPAGE_BPS: int = 5
    TIMEFRAME: str = "1h"
    PROFILE: str = "backtest"

    # для совместимости с кодом брокера/лимитера — безопасные значения:
    EXCHANGE: str = "gateio"
    RATE_PUBLIC_RPM: float = 400.0
    RATE_PUBLIC_BURST: float = 400.0
    RATE_PRIVATE_READ_RPM: float = 200.0
    RATE_PRIVATE_READ_BURST: float = 200.0
    RATE_PRIVATE_WRITE_RPM: float = 120.0
    RATE_PRIVATE_WRITE_BURST: float = 120.0
    BROKER_RETRY_MAX: int = 1
    BROKER_RETRY_BASE_SEC: float = 0.05
    BROKER_RETRY_MAX_SEC: float = 0.2


# -------- Мини-брокер (только fetch_ticker) --------

class _PaperFeedBroker:
    """
    Мини-брокер для бэктеста.
    Нужен только fetch_ticker(); place_order в paper-режиме сам заполняет ордер.
    """
    exchange_name = "gateio"

    def __init__(self, symbol: str):
        self._symbol = symbol
        self._last = 0.0

    def set_price(self, px: float) -> None:
        self._last = float(px)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        # place_order берёт last/close
        return {"symbol": symbol, "last": self._last, "close": self._last}


# -------- Контейнер-обёртка для repos (как в live) --------

class _Repos:
    def __init__(self, con: sqlite3.Connection):
        self.trades_repo = SqliteTradeRepository(con)
        self.positions_repo = SqlitePositionRepository(con)
        # exits_repo не обязателен для smoke-стратегии; оставим best-effort:
        try:
            from crypto_ai_bot.core.storage.repositories.protective_exits import SqliteProtectiveExitsRepository
            self.exits_repo = SqliteProtectiveExitsRepository(con)
        except Exception:
            class _NoExits:
                def list_active(self, **kwargs): return []
                def deactivate(self, *_a, **_k): return None
            self.exits_repo = _NoExits()


# -------- PnL по закрытым сделкам (та же логика что в /telegram) --------

def realized_pnl_summary(con: sqlite3.Connection, symbol: Optional[str] = None) -> Dict[str, Any]:
    if symbol:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' AND symbol=? ORDER BY ts ASC", (symbol,)
        )
    else:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' ORDER BY ts ASC"
        )
    rows = [(int(ts), str(sym), str(side), float(price), float(qty), float(fee))
            for (ts, sym, side, price, qty, fee) in cur.fetchall()]
    if not rows:
        return {"closed_trades": 0, "wins": 0, "losses": 0, "pnl_abs": 0.0, "pnl_pct": 0.0}

    inv: Dict[str, Dict[str, float]] = {}
    realized = 0.0
    realized_cost = 0.0
    wins = losses = closed = 0

    for _, sym, side, px, qty, fee in rows:
        s = inv.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if side == "buy":
            new_qty = s["qty"] + qty
            if new_qty <= 0:
                s["qty"] = 0.0; s["avg"] = 0.0
            else:
                s["avg"] = (s["avg"] * s["qty"] + px * qty) / new_qty if s["qty"] > 0 else px
                s["qty"] = new_qty
        else:
            sell_qty = min(qty, s["qty"]) if s["qty"] > 0 else qty
            pnl = (px - s["avg"]) * sell_qty - fee
            realized += pnl
            realized_cost += s["avg"] * sell_qty
            closed += 1
            if pnl >= 0: wins += 1
            else: losses += 1
            s["qty"] = max(0.0, s["qty"] - sell_qty)
            if s["qty"] == 0.0:
                s["avg"] = 0.0

    pnl_pct = (realized / realized_cost * 100.0) if realized_cost > 0 else 0.0
    return {"closed_trades": closed, "wins": wins, "losses": losses, "pnl_abs": realized, "pnl_pct": pnl_pct}


# -------- Движок --------

@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

Strategy = Any  # протокол: def on_candle(candle, ctx) -> Optional[dict(side='buy'|'sell')]

@dataclass
class EngineResult:
    trades: int
    summary: Dict[str, Any]


class BacktestEngine:
    def __init__(self, *, con: sqlite3.Connection, settings: BacktestSettings):
        self.con = con
        self.settings = settings
        apply_all(self.con)  # идемпотентно
        self.repos = _Repos(self.con)
        self.broker = _PaperFeedBroker(settings.SYMBOL)

    def run(self, *, candles: Iterable[Candle], strategy: Strategy) -> EngineResult:
        trades_before = self._count_trades()
        ctx = {"symbol": self.settings.SYMBOL}

        for c in candles:
            self.broker.set_price(c.close)
            decision = strategy.on_candle(c, ctx)
            if decision and decision.get("side") in ("buy", "sell"):
                eval_and_execute(
                    cfg=self.settings,
                    broker=self.broker,
                    repos=self.repos,
                    symbol=self.settings.SYMBOL,
                    decision={"side": decision["side"]},
                )

        trades_after = self._count_trades()
        summary = realized_pnl_summary(self.con, self.settings.SYMBOL)
        return EngineResult(trades=trades_after - trades_before, summary=summary)

    def _count_trades(self) -> int:
        cur = self.con.execute("SELECT COUNT(1) FROM trades WHERE state='filled'")
        (n,) = cur.fetchone() or (0,)
        return int(n)
