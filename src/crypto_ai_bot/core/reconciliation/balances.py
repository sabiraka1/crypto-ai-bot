from __future__ import annotations

from ..brokers.base import IBroker
from ...utils.logging import get_logger

class BalancesReconciler:
    """
    Мягкая сверка балансов. Только логирует. Если брокер не поддерживает fetch_balance — пропускает.
    """

    def __init__(self, *, broker: IBroker) -> None:
        self._log = get_logger("reconcile.balances")
        self._broker = broker

    async def run_once(self) -> None:
        fetch_balance = getattr(self._broker, "fetch_balance", None)
        if not callable(fetch_balance):
            self._log.info("skip_no_fetch_balance")
            return
        try:
            bal = await fetch_balance()  # type: ignore
            # выводить весь баланс шумно — логируем кратко
            self._log.info("balance_ok", extra={"keys": list(bal.keys())[:5] if isinstance(bal, dict) else "unknown"})
        except Exception as exc:
            self._log.error("fetch_balance_failed", extra={"error": str(exc)})
