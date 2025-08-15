# -*- coding: utf-8 -*-
"""
Unified Bot proxy (Phase 1).
Цель: единая точка импорта бота по пути: crypto_ai_bot.core.bot
Пока проксирует к существующей реализации.
"""
from __future__ import annotations

try:
    from crypto_ai_bot.trading.bot import TradingBot, get_bot  # type: ignore
except Exception:
    class TradingBot:  # type: ignore
        pass
    def get_bot(*args, **kwargs):  # type: ignore
        raise RuntimeError("Legacy TradingBot/get_bot not found")









