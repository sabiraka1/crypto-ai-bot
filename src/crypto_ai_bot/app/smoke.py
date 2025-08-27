from __future__ import annotations

import asyncio
from crypto_ai_bot.app.compose import build_container

async def main() -> int:
    c = build_container()
    # быстрые проверки
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    print("[health]", {"ok": rep.ok, "ts_ms": rep.ts_ms})
    # короткий прогон оркестратора
    c.orchestrator.start()
    await asyncio.sleep(1.0)
    await c.orchestrator.stop()
    print("[orchestrator] start-stop OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
