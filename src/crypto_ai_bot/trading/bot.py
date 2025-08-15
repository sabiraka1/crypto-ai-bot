# -*- coding: utf-8 -*-
"""
Trading bot (Ñ‡Ğ¸ÑÑ‚Ğ°Ñ Ğ²ĞµÑ€ÑĞ¸Ñ, Ğ¸ÑĞ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¾):
- Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ ĞµĞ´Ğ¸Ğ½Ñ‹Ğµ Ğ¸Ğ¼Ğ¿Ğ¾Ñ€Ñ‚Ñ‹ Ğ¸Ğ· core.*
- Ğ²Ğ°Ğ»Ğ¸Ğ´Ğ°Ñ‚Ğ¾Ñ€ ĞºĞ°Ğº validate_features (Ğ°Ğ»Ğ¸Ğ°Ñ)
- PaperStore Ğ³Ğ°Ñ€Ğ°Ğ½Ñ‚Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ½Ğ½Ğ¾ ÑĞ¾Ğ·Ğ´Ğ°Ñ‘Ñ‚ Ğ¿Ğ°Ğ¿ĞºĞ¸/Ñ„Ğ°Ğ¹Ğ»Ñ‹
- singleton-Ğ´Ğ¾ÑÑ‚ÑƒĞ¿ Ñ‡ĞµÑ€ĞµĞ· get_bot(...)

âš ï¸ Ğ˜ÑĞ¿Ñ€Ğ°Ğ²Ğ»ĞµĞ½Ğ¸Ñ Ğ² ÑÑ‚Ğ¾Ğ¹ Ğ²ĞµÑ€ÑĞ¸Ğ¸:
- ĞŸÑ€Ğ°Ğ²Ğ¸Ğ»ÑŒĞ½Ğ°Ñ ÑĞ²ÑĞ·ĞºĞ° Aggregator â†’ Policy: aggregate_features(cfg, exchange, ...) â†’ policy.decide(features, cfg)
- ĞŸĞ¾Ğ»Ğ½Ğ¾ÑÑ‚ÑŒÑ ÑƒĞ±Ñ€Ğ°Ğ½ legacy fuse_scores (Ğ´ÑƒĞ±Ğ»Ğ¸Ñ€Ğ¾Ğ²Ğ°Ğ» Ğ»Ğ¾Ğ³Ğ¸ĞºÑƒ policy)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

# === ĞµĞ´Ğ¸Ğ½Ñ‹Ğµ Ğ¸Ğ¼Ğ¿Ğ¾Ñ€Ñ‚Ñ‹ (Ğ±ĞµĞ· Ñ„Ğ¾Ğ»Ğ»Ğ±ĞµĞºĞ¾Ğ²) ===
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals.aggregator import aggregate_features
from crypto_ai_bot.core.signals.validator import validate as validate_features
from crypto_ai_bot.core.signals.policy import decide as policy_decide

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
        # ÑĞ¾Ğ·Ğ´Ğ°Ñ‘Ğ¼ Ğ´Ğ¸Ñ€ĞµĞºÑ‚Ğ¾Ñ€Ğ¸Ğ¸
        for p in (self.positions_path, self.orders_path, self.pnl_path):
            p.parent.mkdir(parents=True, exist_ok=True)
        # ÑĞ¾Ğ·Ğ´Ğ°Ñ‘Ğ¼ Ñ„Ğ°Ğ¹Ğ»Ñ‹ Ñ Ğ·Ğ°Ğ³Ğ¾Ğ»Ğ¾Ğ²ĞºĞ°Ğ¼Ğ¸/Ğ¿ÑƒÑÑ‚Ñ‹Ğ¼ ÑĞ¾Ğ´ĞµÑ€Ğ¶Ğ¸Ğ¼Ñ‹Ğ¼
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

        # paper store (ÑĞ¾Ğ·Ğ´Ğ°Ñ‘Ñ‚ Ğ¿Ğ°Ğ¿ĞºĞ¸/Ñ„Ğ°Ğ¹Ğ»Ñ‹ ÑĞ°Ğ¼)
        self.paper = PaperStore(
            self.cfg.PAPER_POSITIONS_FILE,
            self.cfg.PAPER_ORDERS_FILE,
            self.cfg.PAPER_PNL_FILE,
        )

        self.positions = []  # Ğ¿Ñ€Ğ¾ÑÑ‚Ğ°Ñ in-memory Ğ²Ğ¸Ñ‚Ñ€Ğ¸Ğ½Ğ° (ĞµÑĞ»Ğ¸ Ğ½ÑƒĞ¶Ğ½Ğ¾)

    # --- Ğ¿ÑƒĞ±Ğ»Ğ¸Ñ‡Ğ½Ñ‹Ğ¹ API (Ğ´Ğ»Ñ Telegram) ---
    def request_market_order(self, side: str, amount: float) -> str:
        side = side.lower()
        if side not in ("buy", "sell"):
            return "side must be buy|sell"

        # Ğ±ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ñ‹Ğµ Ñ€ĞµĞ¶Ğ¸Ğ¼Ñ‹ â†’ Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ Ğ·Ğ°Ğ¿Ğ¸ÑÑ‹Ğ²Ğ°ĞµĞ¼ Â«Ğ±ÑƒĞ¼Ğ°Ğ¶Ğ½Ñ‹Ğ¹Â» Ğ¾Ñ€Ğ´ĞµÑ€
        if self.cfg.SAFE_MODE or self.cfg.PAPER_MODE or not self.cfg.ENABLE_TRADING:
            self.paper.append_order({
                "id": "paper",
                "ts": pd.Timestamp.utcnow().isoformat(),
                "symbol": self.cfg.SYMBOL,
                "side": side,
                "amount": amount,
                "price": 0.0,
            })
            return f"[PAPER] {side} {amount} {self.cfg.SYMBOL}"

        # live-Ğ¾Ñ€Ğ´ĞµÑ€
        try:
            order = self.exchange.create_order(self.cfg.SYMBOL, "market", side, amount)  # type: ignore[attr-defined]
            return f"live order ok: {order}"
        except Exception as e:  # pragma: no cover
            logger.exception("live order failed")
            return f"live order failed: {e}"

    def request_close_position(self) -> str:
        # Ğ—Ğ°Ğ³Ğ»ÑƒÑˆĞºĞ°: Ğ·Ğ°Ğ²Ğ¸ÑĞ¸Ñ‚ Ğ¾Ñ‚ Ñ‚Ğ²Ğ¾ĞµĞ³Ğ¾ Ğ¼ĞµĞ½ĞµĞ´Ğ¶ĞµÑ€Ğ° Ğ¿Ğ¾Ğ·Ğ¸Ñ†Ğ¸Ğ¹
        return "close-position: not implemented here"

    # --- Ğ¾ÑĞ½Ğ¾Ğ²Ğ½Ğ¾Ğ¹ Â«Ñ‚Ğ¸ĞºÂ» ÑÑ‚Ñ€Ğ°Ñ‚ĞµĞ³Ğ¸Ğ¸ ---
    def evaluate(self) -> Dict[str, Any]:
        """
        Ğ¡Ğ¾Ğ±Ğ¸Ñ€Ğ°ĞµÑ‚ Ğ¿Ñ€Ğ¸Ğ·Ğ½Ğ°ĞºĞ¸ Ğ¸ Ğ²Ğ¾Ğ·Ğ²Ñ€Ğ°Ñ‰Ğ°ĞµÑ‚ Ñ€ĞµÑˆĞµĞ½Ğ¸Ğµ.
        ĞŸÑ€Ğ°Ğ²Ğ¸Ğ»ÑŒĞ½Ğ°Ñ Ñ†ĞµĞ¿Ğ¾Ñ‡ĞºĞ° Ğ²Ñ‹Ğ·Ğ¾Ğ²Ğ¾Ğ²:
          - aggregate_features(cfg, exchange, symbol=..., timeframe=..., limit=...)
          - policy.decide(features, cfg)
        """
        feats = aggregate_features(
            self.cfg,
            self.exchange,
            symbol=self.cfg.SYMBOL,
            timeframe=self.cfg.TIMEFRAME,
            limit=self.cfg.AGGREGATOR_LIMIT,
        )
        ok, reason = validate_features(feats, self.cfg)
        if not ok:
            return {"ok": False, "reason": reason, "features": feats}

        decision = policy_decide(feats, self.cfg)
        # Back-compat: Ñ‚Ğ°ĞºĞ¶Ğµ Ğ¾Ñ‚Ğ´Ğ°Ğ´Ğ¸Ğ¼ Ğ²ĞµÑ€Ñ…Ğ½ĞµÑƒÑ€Ğ¾Ğ²Ğ½ĞµĞ²Ñ‹Ğ¹ score
        return {
            "ok": True,
            "decision": decision,
            "score": float(decision.get("score", 0.0)),
            "features": feats,
        }

    # singleton
    @classmethod
    def get_instance(cls, exchange: Any, notifier, settings: Settings) -> "TradingBot":
        if cls._singleton is None:
            cls._singleton = TradingBot(exchange, notifier, settings)
        return cls._singleton

# Ñ„Ğ°Ğ±Ñ€Ğ¸ĞºĞ° Ğ´Ğ»Ñ server/telegram
def get_bot(exchange: Any, notifier, settings: Optional[Settings] = None) -> TradingBot:
    cfg = settings or Settings.build()
    return TradingBot.get_instance(exchange, notifier, cfg)

