from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("reconcile.balances")


def _dec_from(bal: Mapping[str, Any], key: str, default: str = "0") -> Decimal:
    try:
        return dec(str(bal.get(key, default)))
    except Exception:  # noqa: BLE001
        return dec(default)


@dataclass
class BalancesReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> dict[str, str]:
        """
        Fetch balance at broker and normalize values to Decimal strings.
        No side-effects: event publishing / DB writes belong to the caller.
        """
        try:
            bal = await self.broker.fetch_balance(self.symbol)  # dict: free_base, free_quote
        except Exception:  # noqa: BLE001
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


async def reconcile_balances(symbol: str, _storage: Any, broker: Any, _bus: Any, _settings: Any) -> None:
    """
    Thin wrapper for orchestrator-compat: call the reconciler and return.
    Publishing/writing is left to the application layer to avoid mixed responsibilities.
    """
    rec = BalancesReconciler(broker=broker, symbol=symbol)
    _ = await rec.run_once()
