from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("cli.health_monitor")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def _fetch_health(url: str, timeout: float) -> dict[str, Any]:  # noqa: ASYNC109
    try:
        resp = await aget(url, timeout=timeout)
        return {
            "status_code": resp.status_code,
            "ok": resp.status_code == 200,
            "text": resp.text,
            "json": (
                resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            ),
        }
    except Exception:  # noqa: BLE001
        _log.error("health_fetch_failed", extra={"url": url}, exc_info=True)
        return {"status_code": 0, "ok": False, "text": "", "json": None}


async def _oneshot(url: str, timeout: float) -> int:  # noqa: ASYNC109
    res = await _fetch_health(url, timeout)
    pretty = res.get("json") or res.get("text")
    try:
        out = (
            json.dumps(pretty, ensure_ascii=False, indent=2)
            if isinstance(pretty, dict | list)
            else str(pretty)
        )
    except Exception:  # noqa: BLE001
        out = str(pretty)
    print(out)
    return 0 if res.get("ok") else 1


async def _watch(url: str, timeout: float, interval: float) -> int:  # noqa: ASYNC109
    while True:
        code = await _oneshot(url, timeout)
        await asyncio.sleep(max(0.5, interval))
        if code != 0:
            # Ѿ ю,  ѵ ѵѿѵ
            _log.warning("health_not_ok", extra={"url": url})
    # сѸ
    # return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP health monitor")
    parser.add_argument("--url", default=_env("HEALTH_URL", "http://127.0.0.1:8000/health"))
    parser.add_argument("--oneshot", action="store_true", help="single check and exit with code")
    parser.add_argument("--timeout", type=float, default=float(_env("HTTP_TIMEOUT_SEC", "30")))
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    if args.oneshot:
        raise SystemExit(asyncio.run(_oneshot(args.url, args.timeout)))
        # ѽ ю
        try:
            asyncio.run(_watch(args.url, args.timeout, args.interval))
        except KeyboardInterrupt:
            print("\nstopped by user")
            raise SystemExit(0) from None


if __name__ == "__main__":
    main()
