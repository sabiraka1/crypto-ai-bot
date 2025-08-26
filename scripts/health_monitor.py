#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.logging import get_logger

log = get_logger("health_monitor")


@dataclass
class HealthState:
    ok: bool
    latency_ms: int
    details: Dict[str, Any]


def _http_get(url: str, timeout: float) -> tuple[int, bytes, int]:
    t0 = time.time()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - controlled URL
        body = resp.read()
        code = int(resp.getcode() or 0)
    dt_ms = int((time.time() - t0) * 1000)
    return code, body, dt_ms


def _parse_health(body: bytes) -> Dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return {}


def _send_telegram(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(endpoint, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec - Telegram API
        _ = resp.read()


def check_once(url: str, timeout: float, latency_warn_ms: int) -> HealthState:
    code, body, dt_ms = _http_get(url, timeout)
    payload = _parse_health(body)

    ok = False
    if code == 200:
        if isinstance(payload, dict) and "ok" in payload:
            ok = bool(payload.get("ok"))
        else:
            # Если эндпойнт не возвращает {ok: bool}, но ответ 200 — считаем OK
            ok = True
    details: Dict[str, Any] = payload if isinstance(payload, dict) else {"raw": body[:256].decode("utf-8", "ignore")}

    # деградация по латентности
    if dt_ms > latency_warn_ms:
        details.setdefault("warnings", []).append({"latency_ms": dt_ms, "threshold": latency_warn_ms})

    return HealthState(ok=ok, latency_ms=dt_ms, details=details)


def run_watch(url: str, timeout: float, interval: float, latency_warn_ms: int,
              tg_token: Optional[str], tg_chat: Optional[str]) -> int:
    last_ok: Optional[bool] = None
    while True:
        try:
            st = check_once(url, timeout, latency_warn_ms)
            msg = f"health={st.ok} latency={st.latency_ms}ms"
            log.info("health", extra={"ok": st.ok, "latency_ms": st.latency_ms})
            print(msg)

            if last_ok is None:
                last_ok = st.ok
            elif st.ok != last_ok:
                # смена статуса — шлём оповещение (если настроен Telegram)
                if tg_token and tg_chat:
                    icon = "✅" if st.ok else "🚨"
                    txt = (
                        f"{icon} <b>Health status changed</b>\n"
                        f"URL: {url}\n"
                        f"OK: {st.ok}\n"
                        f"Latency: {st.latency_ms} ms\n"
                    )
                    try:
                        _send_telegram(tg_token, tg_chat, txt, parse_mode="HTML")
                    except Exception as exc:
                        log.error("telegram_send_failed", extra={"error": str(exc)})
                last_ok = st.ok
        except Exception as exc:
            log.error("health_check_failed", extra={"error": str(exc)})
            print(f"error: {exc}")
        time.sleep(interval)
    # unreachable


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Simple /health monitor with optional Telegram alerts")
    ap.add_argument("command", choices=["check", "watch"])  # one-off или постоянный
    ap.add_argument("--url", default=os.getenv("HEALTH_URL", "http://localhost:8000/health"))
    ap.add_argument("--timeout", type=float, default=float(os.getenv("HEALTH_TIMEOUT", "5")))
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--latency-warn-ms", type=int, default=1500)
    ap.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN"))
    ap.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_ALERT_CHAT_ID"))

    args = ap.parse_args(argv)

    if args.command == "check":
        st = check_once(args.url, args.timeout, args.latency_warn_ms)
        print(json.dumps({"ok": st.ok, "latency_ms": st.latency_ms, "details": st.details}, ensure_ascii=False))
        return 0 if st.ok else 2

    if args.command == "watch":
        return run_watch(
            url=args.url,
            timeout=args.timeout,
            interval=args.interval,
            latency_warn_ms=args.latency_warn_ms,
            tg_token=args.telegram_bot_token,
            tg_chat=args.telegram_chat_id,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())