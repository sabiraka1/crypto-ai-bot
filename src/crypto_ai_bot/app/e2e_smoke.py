from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

# запускать как:  python -m crypto_ai_bot.app.e2e_smoke
from .compose import build_container


async def main() -> int:
    c = build_container()
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    out: Dict[str, Any] = {
        "ok": rep.ok,
        "symbol": c.settings.SYMBOL,
        "components": rep.components,
        "ts_ms": rep.ts_ms,
        "mode": c.settings.MODE,
        "exchange": c.settings.EXCHANGE,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0 if rep.ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
