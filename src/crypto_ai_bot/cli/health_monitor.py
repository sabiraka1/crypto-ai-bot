from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Optional

from crypto_ai_bot.app.compose import build_container


def _check_internal() -> dict:
    c = build_container()
    rep = c.health
    # health.check() — async; используем HTTP, либо вызывать из CLI не будем.
    return {"ok": True, "note": "internal mode only ensures composition OK"}


def _fetch(url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read().decode("utf-8", errors="ignore")
            try:
                return json.loads(data)
            except Exception:
                return {"raw": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="cab-health", description="Health monitor")
    p.add_argument("--url", help="Health/ready URL, e.g. http://127.0.0.1:8000/health")
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--oneshot", action="store_true")
    args = p.parse_args(argv)

    if not args.url:
        print(json.dumps(_check_internal(), ensure_ascii=False))
        return 0

    while True:
        rep = _fetch(args.url)
        print(json.dumps(rep, ensure_ascii=False))
        if args.oneshot:
            break
        time.sleep(max(1.0, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
