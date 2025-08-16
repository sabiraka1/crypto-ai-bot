# src/crypto_ai_bot/core/bot.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases import place_order as uc_place_order
from crypto_ai_bot.core.use_cases import eval_and_execute as uc_eval_and_execute
from crypto_ai_bot.core.positions.manager import PositionManager
from crypto_ai_bot.core.storage.repositories import (
    TradeRepositorySQLite,
    PositionRepositorySQLite,
    SnapshotRepositorySQLite,
    AuditRepositorySQLite,
)
from crypto_ai_bot.utils import metrics


@dataclass
class Bot:
    """
    Тонкая фасада над use-cases: даёт стабильный API слою app (web/telegram).
    Не содержит бизнес-логики: всё внутри use-cases + signals.policy.
    """
    cfg: Any
    broker: Any
    con: Any

    # --- публичный API для app/adapters ---

    def evaluate(self, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        sym = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        tf = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        lm = int(limit or getattr(self.cfg, "FEATURE_LIMIT", 300))
        return uc_evaluate(self.cfg, self.broker, symbol=sym, timeframe=tf, limit=lm)

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        return uc_place_order(self.cfg, self.broker, self.con, decision)

    def eval_and_execute(self, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        sym = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        tf = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        lm = int(limit or getattr(self.cfg, "FEATURE_LIMIT", 300))
        return uc_eval_and_execute(self.cfg, self.broker, self.con, symbol=sym, timeframe=tf, limit=lm)

    def get_status(self) -> Dict[str, Any]:
        """
        Статус бота: баланс, открытые позиции, экспозиция/PNL.
        """
        pm = PositionManager(
            con=self.con,
            broker=self.broker,
            trades=TradeRepositorySQLite(self.con),
            positions=PositionRepositorySQLite(self.con),
            audit=AuditRepositorySQLite(self.con),
        )
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
