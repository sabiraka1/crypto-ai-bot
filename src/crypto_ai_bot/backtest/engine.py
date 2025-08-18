# backtest/engine.py
from __future__ import annotations
from typing import Iterable, Dict, Any, Optional
from crypto_ai_bot.core.analytics.pnl import realized_pnl_summary as _realized_pnl_summary

__all__ = ["realized_pnl_summary"]

def realized_pnl_summary(trades: Iterable[Dict[str, Any]], symbol: Optional[str] = None) -> Dict[str, float]:
    return _realized_pnl_summary(trades, symbol)
