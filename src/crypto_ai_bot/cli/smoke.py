from __future__ import annotations

import argparse
import asyncio
import importlib
import os

from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("cli.smoke")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def _ping(url: str, timeout: float) -> bool:  # noqa: ASYNC109
    try:
        resp = await aget(url, timeout=timeout)
        _log.info("smoke_ping", extra={"url": url, "status": resp.status_code})
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        _log.error("smoke_ping_failed", extra={"url": url}, exc_info=True)
        return False


def _import_ok(module: str) -> bool:
    try:
        importlib.import_module(module)
        _log.info("import_ok", extra={"module": module})
        return True
    except Exception:  # noqa: BLE001
        _log.error("import_failed", extra={"module": module}, exc_info=True)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-check for crypto-ai-bot")
    parser.add_argument("--url", default=_env("HEALTH_URL", ""), help="optional /health url to ping")
    parser.add_argument("--timeout", type=float, default=float(_env("HTTP_TIMEOUT_SEC", "30")))
    args = parser.parse_args()

    # 1) Сµ
    ok = True
    ok &= _import_ok("crypto_ai_bot.app.server")
    ok &= _import_ok("crypto_ai_bot.app.compose")
    ok &= _import_ok("crypto_ai_bot.core.infrastructure.events.bus")
    ok &= _import_ok("crypto_ai_bot.core.infrastructure.events.redis_bus")

    # 2) СёСЅС№ HTTP-
    if args.url:
        ok &= asyncio.run(_ping(args.url, args.timeout))

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
