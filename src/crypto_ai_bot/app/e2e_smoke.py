from __future__ import annotations

import asyncio
from typing import Any

from .compose import build_container
from ..utils.logging import get_logger

log = get_logger("e2e.smoke")


async def run(cycles: int = 2) -> dict[str, Any]:
    """Минимальный e2e‑смок: поднимаем контейнер, запускаем оркестр, ждём N циклов eval.
    Работает в paper/live. Для live убедись, что API‑ключи заданы и EXCHANGE поддерживается CCXT.
    """
    c = build_container()
    orch = c.orchestrator
    orch.start()

    eval_t = float(getattr(c.settings, "EVAL_INTERVAL_SEC", 60))
    wait_s = max(1.0, eval_t) * cycles + 2.0

    log.info("orchestrator_started", extra={
        "symbol": c.settings.SYMBOL,
        "eval_interval_s": eval_t,
        "cycles": cycles,
        "wait_s": wait_s,
    })

    try:
        await asyncio.sleep(wait_s)
        status = orch.status()
        log.info("orchestrator_status", extra=status)
        return {"ok": True, "status": status, "settings": c.settings.to_dict()}
    finally:
        await orch.stop()
        log.info("orchestrator_stopped")


if __name__ == "__main__":
    asyncio.run(run())