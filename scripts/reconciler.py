#!/usr/bin/env python3
from __future__ import annotations
import asyncio
from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.orchestrator import Orchestrator
async def main() -> None:
    c = build_container()
    orch = Orchestrator(c.settings, c.broker, c.trades_repo, c.positions_repo, c.exits_repo, c.idempotency_repo, c.bus)
    await orch._tick_reconcile_once()  # однократная сверка
if __name__ == "__main__":
    asyncio.run(main())
