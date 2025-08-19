from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.adapters.telegram import handle_update
from crypto_ai_bot.core.orchestrator import Orchestrator


class RedactFilter(logging.Filter):
    """
    Маскирует секреты в логах (best-effort, не ломает формат сообщений).
    """
    KEYS = ("API_KEY", "API_SECRET", "TELEGRAM_TOKEN", "GATEIO_KEY", "GATEIO_SECRET", "DB_URL")
    RE = re.compile(r"(?i)\b(" + "|".join(re.escape(k) for k in KEYS) + r")\b\s*[:=]\s*([^\s,;]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = str(record.getMessage())
            # замена только в представлении; исходный record.msg оставляем
            masked = self.RE.sub(lambda m: f"{m.group(1)}=<redacted>", msg)
            if masked != msg:
                record.msg = masked
                record.args = ()
        except Exception:
            pass
        return True


def _install_redaction():
    root = logging.getLogger()
    root.addFilter(RedactFilter())


def _safe(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_redaction()

    container = build_container()
    app.state.container = container

    if hasattr(container, "bus") and hasattr(container.bus, "start"):
        await container.bus.start()

    app.state.orchestrator = Orchestrator(
        settings=container.settings,
        broker=container.broker,
        trades_repo=container.trades_repo,
        positions_repo=container.positions_repo,
        exits_repo=getattr(container, "exits_repo", None),
        idempotency_repo=getattr(container, "idempotency_repo", None),
        bus=container.bus,
        limiter=getattr(container, "limiter", None),
        risk_manager=getattr(container, "risk_manager", None),
    )
    await app.state.orchestrator.start()

    try:
        yield
    finally:
        # Graceful: остановить тики и дождаться flush очередей шины
        try:
            if getattr(app.state, "orchestrator", None):
                await app.state.orchestrator.stop()
        except Exception:
            pass
        try:
            if hasattr(container, "bus") and hasattr(container.bus, "stop"):
                await container.bus.stop()
        except Exception:
            pass
        # закрываем БД/репозитории, если у них есть close()
        for name in ("trades_repo", "positions_repo", "exits_repo", "idempotency_repo", "storage", "db"):
            try:
                obj = getattr(container, name, None)
                if obj and hasattr(obj, "close"):
                    obj.close()
            except Exception:
                pass


def create_app() -> FastAPI:
    application = FastAPI(title="crypto-ai-bot", version="1.0", lifespan=lifespan)

    @application.get("/", tags=["meta"])
    async def root():
        return {"ok": True, "name": "crypto-ai-bot"}

    @application.get("/ready", tags=["meta"])
    async def ready():
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {"running": True}
        ok = bool(bus_h.get("running"))
        return JSONResponse({"ready": ok, "bus": bus_h}, status_code=200 if ok else 503)

    @application.get("/health", tags=["meta"])
    async def health():
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {"running": True}
        details: Dict[str, Any] = {
            "mode": getattr(c.settings, "MODE", "paper"),
            "symbol": getattr(c.settings, "SYMBOL", "BTC/USDT"),
            "timeframe": getattr(c.settings, "TIMEFRAME", "1h"),
            "bus": bus_h,
            "pending_orders": _safe(c.trades_repo, "count_pending", lambda: 0)(),
            "cb": getattr(getattr(c, "broker", None), "cb", None).metrics() if getattr(getattr(c, "broker", None), "cb", None) else None,
        }
        return JSONResponse({"ok": True, "details": details})

    @application.get("/metrics", tags=["meta"])
    async def metrics():
        try:
            from crypto_ai_bot.utils import metrics as m  # type: ignore
            if hasattr(m, "export"):
                return PlainTextResponse(m.export())
        except Exception:
            pass
        c = application.state.container
        bus_h = c.bus.health() if hasattr(c.bus, "health") else {}
        text = []
        for k, v in bus_h.items():
            text.append(f"app_bus_{k} {v}")
        cb = getattr(getattr(c, "broker", None), "cb", None)
        if cb:
            s = cb.metrics()
            for k, v in s.items():
                if k == "errors_by_kind":
                    for kk, vv in (v or {}).items():
                        text.append(f"cb_errors_by_kind{{kind=\"{kk}\"}} {vv}")
                else:
                    text.append(f"cb_{k} {v if v is not None else 0}")
        return PlainTextResponse("\n".join(text) + "\n")

    @application.post("/telegram/webhook", tags=["adapters"])
    async def telegram_webhook(request: Request):
        body = await request.body()
        c = application.state.container
        return await handle_update(application, body, c)

    return application


app = create_app()
