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
    """Безопасно извлекаем Decimal из словаря баланса."""
    try:
        return dec(str(bal.get(key, default)))
    except Exception:  # noqa: BLE001
        return dec(default)


@dataclass
class BalancesReconciler:
    """
    Забирает баланс у брокера по символу и нормализует значения.
    Сайд-эффектов не делает (паблиш/БД — на уровне вызывающей логики).
    """

    broker: BrokerPort
    symbol: str

    async def run_once(self) -> dict[str, str]:
        try:
            # ожидается: {"free_base": Decimal|num|str, "free_quote": Decimal|num|str}
            bal = await self.broker.fetch_balance(self.symbol)
            if not isinstance(bal, Mapping):
                _log.error(
                    "balance_invalid_payload", extra={"symbol": self.symbol, "type": type(bal).__name__}
                )
                return {"ok": "false", "reason": "invalid_payload"}
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


# Совместимый тонкий враппер для оркестратора
async def reconcile_balances(symbol: str, _storage: Any, broker: Any, _bus: Any, _settings: Any) -> None:
    rec = BalancesReconciler(broker=broker, symbol=symbol)
    _ = await rec.run_once()  # результат возвращаем в вызывающий слой, если нужно
