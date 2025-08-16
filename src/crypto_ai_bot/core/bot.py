from __future__ import annotations

from typing import Any, Optional

from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute

class TradingBot:
    """
    Тонкая фасада: использует фабрику брокера и публичные use-cases.
    """
    def __init__(self, cfg, broker=None, **repos) -> None:
        self.cfg = cfg
        self.broker = broker or create_broker(cfg)
        self.repos = repos

    def evaluate(self, *, symbol: Optional[str]=None, timeframe: Optional[str]=None, limit: Optional[int]=None) -> dict:
        symbol = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        timeframe = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        limit = int(limit or getattr(self.cfg, "DEFAULT_LIMIT", 300))
        return evaluate(self.cfg, self.broker, symbol=symbol, timeframe=timeframe, limit=limit, **self.repos)

    def eval_and_execute(self, *, symbol: Optional[str]=None, timeframe: Optional[str]=None, limit: Optional[int]=None) -> dict:
        symbol = symbol or getattr(self.cfg, "SYMBOL", "BTC/USDT")
        timeframe = timeframe or getattr(self.cfg, "TIMEFRAME", "1h")
        limit = int(limit or getattr(self.cfg, "DEFAULT_LIMIT", 300))
        return eval_and_execute(self.cfg, self.broker, symbol=symbol, timeframe=timeframe, limit=limit, **self.repos)

    def get_status(self) -> dict:
        return {
            "mode": getattr(self.cfg, "MODE", "paper"),
            "symbol": getattr(self.cfg, "SYMBOL", "BTC/USDT"),
            "timeframe": getattr(self.cfg, "TIMEFRAME", "1h"),
        }
