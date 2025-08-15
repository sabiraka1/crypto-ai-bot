# -*- coding: utf-8 -*-
"""
Clean trading bot module.
- Uses unified Settings from core.settings
- Imports signals from core.signals.*
- Keeps fuse_scores from trading.signals.score_fusion
- Robust PaperStore that auto-creates directories/files
- Exposes get_bot(exchange, notifier, settings) singleton
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

try:
    # unified config
    from crypto_ai_bot.core.settings import Settings
    from crypto_ai_bot.core.signals.aggregator import aggregate_features
    from crypto_ai_bot.core.signals.validator import validate_features
    from crypto_ai_bot.core.signals.policy import decide as policy_decide
except Exception:
    # fallback paths (kept for compatibility with older trees)
    from crypto_ai_bot.core.settings import Settings  # type: ignore
    from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features  # type: ignore
    from crypto_ai_bot.trading.signals.signal_validator import validate_features  # type: ignore
    from crypto_ai_bot.trading.signals.entry_policy import decide as policy_decide  # type: ignore

# keep your fusion
try:
    from crypto_ai_bot.trading.signals.score_fusion import fuse_scores
except Exception:  # pragma: no cover
    def fuse_scores(*_, **__):  # type: ignore
        return 0.5

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

# ---------- PaperStore (robust) ----------
@dataclass
class PaperStore:
    positions_path: Path
    orders_path: Path
    pnl_path: Path

    def __init__(self, positions: str, orders: str, pnl: str) -> None:
        self.positions_path = Path(positions)
        self.orders_path = Path(orders)
        self.pnl_path = Path(pnl)
        self._ensure_files()

    def _ensure_files(self) -> None:
        # create parent dirs
        for p in [self.positions_path, self.orders_path, self.pnl_path]:
            p.parent.mkdir(parents=True, exist_ok=True)
        # touch files
        if not self.positions_path.exists():
            self.positions_path.write_text("[]", encoding="utf-8")
        if not self.orders_path.exists():
            self.orders_path.write_text("id,ts,symbol,side,amount,price\n", encoding="utf-8")
        if not self.pnl_path.exists():
            self.pnl_path.write_text("ts,pnl\n", encoding="utf-8")

    def append_order(self, row: Dict[str, Any]) -> None:
        self._ensure_files()
        with self.orders_path.open("a", encoding="utf-8") as f:
            f.write("{id},{ts},{symbol},{side},{amount},{price}\n".format(**row))

# ---------- Bot core ----------
class TradingBot:
    _singleton: Optional["TradingBot"] = None

    def __init__(self, exchange: Any, notifier, settings: Settings) -> None:
        self.exchange = exchange
        self.notify = notifier
        self.cfg = settings
        # paper store
        self.paper = PaperStore(
            self.cfg.PAPER_POSITIONS_FILE,
            self.cfg.PAPER_ORDERS_FILE,
            self.cfg.PAPER_PNL_FILE,
        )
        self.positions = []  # simple in-memory view

    # --------- public API (Telegram uses) ---------
    def request_market_order(self, side: str, amount: float) -> str:
        side = side.lower()
        if side not in ("buy", "sell"):
            return "side must be buy|sell"
        if self.cfg.SAFE_MODE or self.cfg.PAPER_MODE or not self.cfg.ENABLE_TRADING:
            # paper/log only
            self.paper.append_order({
                "id": "paper",
                "ts": pd.Timestamp.utcnow().isoformat(),
                "symbol": self.cfg.SYMBOL,
                "side": side,
                "amount": amount,
                "price": 0.0,
            })
            return f"[PAPER] {side} {amount} {self.cfg.SYMBOL}"
        # live
        try:
            order = self.exchange.create_order(self.cfg.SYMBOL, "market", side, amount)  # type: ignore[attr-defined]
            return f"live order ok: {order}"
        except Exception as e:  # pragma: no cover
            logger.exception("live order failed")
            return f"live order failed: {e}"

    def request_close_position(self) -> str:
        # placeholder (depends on your PM)
        return "close-position: not implemented here"

    # --------- strategy tick ---------
    def evaluate(self) -> Dict[str, Any]:
        feats = aggregate_features(self.cfg.SYMBOL, self.cfg.TIMEFRAME, limit=self.cfg.AGGREGATOR_LIMIT)
        ok, reason = validate_features(feats, self.cfg)
        if not ok:
            return {"ok": False, "reason": reason, "features": feats}
        rule_score = fuse_scores(feats)
        decision = policy_decide(rule_score, feats, self.cfg)
        return {"ok": True, "decision": decision, "score": rule_score, "features": feats}

    # singleton access
    @classmethod
    def get_instance(cls, exchange: Any, notifier, settings: Settings) -> "TradingBot":
        if cls._singleton is None:
            cls._singleton = TradingBot(exchange, notifier, settings)
        return cls._singleton

# factory kept for server/telegram
def get_bot(exchange: Any, notifier, settings: Optional[Settings] = None) -> TradingBot:
    cfg = settings or Settings.build()
    return TradingBot.get_instance(exchange, notifier, cfg)




