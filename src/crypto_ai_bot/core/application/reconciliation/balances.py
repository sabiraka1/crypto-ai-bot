from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from decimal import Decimal

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("reconcile.balances")


def _dec_from(bal: Mapping[str, Any], key: str, default: str = "0") -> Decimal:
    try:
        return dec(str(bal.get(key, default)))
    except Exception:
        return dec(default)


@dataclass
class BalancesReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> dict[str, str]:
        """
        Получает баланс у брокера и нормализует значения к строкам Decimal.
        Никаких side-effects: публикации событий/запись в БД делает вызывающий слой.
        """
        try:
            bal = await self.broker.fetch_balance(self.symbol)  # dict: free_base, free_quote
        except Exception:
            _log.error("balance_fetch_failed", extra={"symbol": self.symbol}, exc_info=True)
            return {"ok": "false", "reason": "broker_error"}

        free_base = _dec_from(bal, "free_base")
        free_quote = _dec_from(bal, "free_quote")

        if free_base < 0 or free_quote < 0:
            _log.warning(
                "balance_negative_values",
                extra={"symbol": self.symbol, "free_base": str(free_base), "free_quote": str(free_quote)},
            )

        return {"ok": "true", "free_base": str(free_base), "free_quote": str(free_quote)}


async def reconcile_balances(symbol: str, storage: Any, broker: Any, bus: Any, settings: Any) -> None:
    """
    Функция-обёртка для совместимости с orchestrator: сейчас просто вызывает Reconciler.
    Паблишинг в шину/запись в БД — по месту вызова (application-слой), чтобы не смешивать ответственность.
    """
    rec = BalancesReconciler(broker=broker, symbol=symbol)
    _ = await rec.run_once()
