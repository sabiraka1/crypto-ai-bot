# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.risk import rules
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)


class RiskManager:
    """
    Координирует вызов правил риск-менеджмента в корректном порядке.
    Никаких чтений ENV — только settings, переданный извне.
    """
    def __init__(self, *, settings, broker, trades_repo, positions_repo):
        self.settings = settings
        self.broker = broker
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo

    async def evaluate(self, *, symbol: str, side: str, notional_usd: float) -> Dict[str, Any]:
        try:
            return await rules.evaluate_all(
                settings=self.settings,
                broker=self.broker,
                positions_repo=self.positions_repo,
                trades_repo=self.trades_repo,
                symbol=symbol,
                side=side,
                notional_usd=notional_usd,
            )
        except Exception as e:
            logger.exception("risk_evaluate_failed: %s", e)
            return {"ok": False, "reason": "risk_evaluate_failed", "error": str(e)}
