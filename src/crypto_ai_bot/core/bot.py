# src/crypto_ai_bot/core/bot.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases import place_order as uc_place_order
from crypto_ai_bot.core.use_cases import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.positions.manager import PositionManager  # для get_status()
from crypto_ai_bot.core.storage.repositories import (
    TradeRepositorySQLite,
    PositionRepositorySQLite,
    SnapshotRepositorySQLite,
    AuditRepositorySQLite,
    IdempotencyRepositorySQLite,
)
from crypto_ai_bot.utils import metrics


@dataclass
class Bot:
    cfg: Any
    broker: Any
    con: Any

    def _repos(self):
        con = self.con
        return (
            TradeRepositorySQLite(con),
            PositionRepositorySQLite(con),
            SnapshotRepositorySQLite(con),
            AuditRepositorySQLite(con),
            IdempotencyRepositorySQLite(con),
        )

    def evaluate(self, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        sym = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        tf  = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        lm  = int(limit or getattr(self.cfg, "FEATURE_LIMIT", 300))
        return uc_evaluate(self.cfg, self.broker, symbol=sym, timeframe=tf, limit=lm)

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        trades, positions, snapshots, audit, idem = self._repos()
        return uc_place_order(
            self.cfg, self.broker, self.con, decision,
            trades=trades, positions=positions, audit=audit, idem=idem
        )

    def eval_and_execute(self, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        sym = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        tf  = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        lm  = int(limit or getattr(self.cfg, "FEATURE_LIMIT", 300))
        trades, positions, snapshots, audit, idem = self._repos()
        return uc_eval_and_execute(
            self.cfg, self.broker, self.con,
            symbol=sym, timeframe=tf, limit=lm,
            trades=trades, positions=positions, audit=audit, idem=idem
        )

    def get_status(self) -> Dict[str, Any]:
        trades, positions, snapshots, audit, idem = self._repos()
        pm = PositionManager(con=self.con, broker=self.broker, trades=trades, positions=positions, audit=audit)
        snap = pm.get_snapshot()
        try:
            balance = self.broker.fetch_balance()
        except Exception as e:
            balance = {"error": repr(e)}
        metrics.inc("bot_status_total", {})
        return {
            "mode": getattr(self.cfg, "MODE", "unknown"),
            "symbol": getattr(self.cfg, "SYMBOL", "BTC/USDT"),
            "timeframe": getattr(self.cfg, "TIMEFRAME", "1h"),
            "balance": balance,
            "positions": snap,
        }


def get_bot(*, cfg, broker, con) -> Bot:
    return Bot(cfg=cfg, broker=broker, con=con)
