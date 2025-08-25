from __future__ import annotations

from ..brokers.base import IBroker
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer


class BalancesReconciler:
    """
    Мягкая сверка балансов:
    - Если брокер не умеет fetch_balance — пропускаем
    - Логируем наличие и несколько ключей, метрики — для мониторинга
    """

    def __init__(self, *, broker: IBroker) -> None:
        self._log = get_logger("reconcile.balances")
        self._broker = broker

    async def run_once(self) -> None:
        fetch_balance = getattr(self._broker, "fetch_balance", None)
        if not callable(fetch_balance):
            self._log.info("skip_no_fetch_balance")
            return

        with timer("reconcile_balances_ms", {}):
            try:
                bal = await fetch_balance()  # type: ignore
                keys = list(bal.keys())[:5] if isinstance(bal, dict) else []
                inc("reconcile_balances", {"status": "ok"})
                self._log.info("balance_ok", extra={"keys": keys})
            except Exception as exc:
                inc("reconcile_balances", {"status": "failed"})
                self._log.error("fetch_balance_failed", extra={"error": str(exc)})
