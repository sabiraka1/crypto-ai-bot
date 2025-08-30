from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Any

from crypto_ai_bot.core.application.ports import BrokerPort, StoragePort, EventBusPort, SafetySwitchPort
from crypto_ai_bot.core.application.use_cases.eval_and_execute import eval_and_execute
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.budget_guard import check as budget_check

_log = get_logger("loop.eval")


class EvalLoop:
    """
    Отдельный цикл оценки стратегии и исполнения сделок.
    Не содержит инфраструктурных импортов; всё — через порты и колбэки.
    """

    def __init__(
        self,
        *,
        symbol: str,
        storage: StoragePort,
        broker: BrokerPort,
        bus: EventBusPort,
        settings: Any,
        risk_manager: Any,
        protective_exits: Any,
        eval_interval_sec: float,
        dms: Optional[SafetySwitchPort],
        force_eval_action: Optional[str],
        fee_estimate_pct: Decimal,
        is_paused: Callable[[], bool],
        fixed_amount_resolver: Callable[[str], Decimal],
        flight_cm: Callable[[], Awaitable],  # async context manager factory: `async with flight_cm(): ...`
        on_budget_exceeded: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.symbol = symbol
        self.storage = storage
        self.broker = broker
        self.bus = bus
        self.settings = settings
        self.risk = risk_manager
        self.exits = protective_exits
        self.eval_interval_sec = float(max(eval_interval_sec, 0.1))
        self.dms = dms
        self.force_eval_action = force_eval_action
        self.fee_estimate_pct = dec(str(fee_estimate_pct))
        self.is_paused = is_paused
        self.fixed_amount_for = fixed_amount_resolver
        self.flight_cm = flight_cm
        self.on_budget_exceeded = on_budget_exceeded
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    async def run(self) -> None:
        while not self._stopping:
            try:
                if self.is_paused():
                    await asyncio.sleep(min(1.0, self.eval_interval_sec))
                else:
                    over = budget_check(self.storage, self.symbol, self.settings)
                    if over:
                        await self.on_budget_exceeded({"symbol": self.symbol, **over, "ts_ms": now_ms()})
                        await asyncio.sleep(self.eval_interval_sec)
                        continue

                    async with self.flight_cm():
                        fixed_amt = self.fixed_amount_for(self.symbol)
                        await eval_and_execute(
                            symbol=self.symbol,
                            storage=self.storage,
                            broker=self.broker,
                            bus=self.bus,
                            exchange=self.settings.EXCHANGE,
                            fixed_quote_amount=fixed_amt,
                            idempotency_bucket_ms=self.settings.IDEMPOTENCY_BUCKET_MS,
                            idempotency_ttl_sec=self.settings.IDEMPOTENCY_TTL_SEC,
                            force_action=self.force_eval_action,
                            risk_manager=self.risk,
                            protective_exits=self.exits,
                            settings=self.settings,
                            fee_estimate_pct=self.fee_estimate_pct,
                        )
                        if self.dms:
                            self.dms.beat()
            except Exception as exc:
                _log.error("eval_loop_failed", extra={"symbol": self.symbol, "error": str(exc)})
            await asyncio.sleep(self.eval_interval_sec)
