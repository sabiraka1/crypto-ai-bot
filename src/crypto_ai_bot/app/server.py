# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.orchestrator import Orchestrator

# если у вас хендлер телеграма в виде handle_update(container, payload)
# — раскомментируйте следующую строку и используйте «Новый вариант» ниже
# from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle  # (container, payload)

# если в проекте ещё используется старый вариант handle_update(app, body, container),
# оставим мягкую зависимость:
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_legacy  # type: ignore
except Exception:  # pragma: no cover
    tg_handle_legacy = None  # type: ignore

logger = logging.getLogger("app.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # build DI
    container = build_container()
    app.state.container = container
    
    # EventBus
    if hasattr(container, "bus") and hasattr(container.bus, "start"):
        await container.bus.start()
    
    # Orchestrator - ИСПРАВЛЕНО
    orch = Orchestrator(
        settings=container.settings,
        broker=container.broker,
        trades_repo=container.trades_repo,
        positions_repo=container.positions_repo,
        exits_repo=container.exits_repo,
        idempotency_repo=container.idempotency_repo,
        bus=container.bus,
        risk_manager=None
    )
    app.state.orchestrator = orch
    await orch.start()
    
    try:
        yield
    finally:
        # graceful shutdown
        try:
            if hasattr(app.state, "orchestrator"):
                await app.state.orchestrator.stop()
        except Exception:
            pass
        try:
            if hasattr(container, "bus") and hasattr(container.bus, "stop"):
                await container.bus.stop()
        except Exception:
            pass
        # закрываем репозитории/соединения
        for name in ("trades_repo", "positions_repo", "exits_repo", "idempotency_repo", "storage", "db", "con"):
            try:
                obj = getattr(container, name, None)
                if obj and hasattr(obj, "close"):
                    obj.close()
            except Exception:
                pass


def create_app() -> FastAPI:
    app = FastAPI(title="crypto-ai-bot", version="1.0", lifespan=lifespan)

    @app.get("/health", tags=["infra"])
    async def health():
        c = app.state.container
        # базовый health + пару показателей
        broker_ok = True
        try:
            # не блокируем loop
            t0 = time.time()
            tk = await asyncio.to_thread(c.broker.fetch_ticker, getattr(c.settings, "SYMBOL", "BTC/USDT"))
            latency = float(tk.get("info", {}).get("elapsed", 0.0)) if isinstance(tk, dict) else 0.0
            broker_ok = (tk or {}) != {}
        except Exception:
            broker_ok = False
            latency = 0.0

        return JSONResponse({
            "ok": broker_ok,
            "exchange_latency_ms": latency,
            "cb_state": getattr(getattr(c.broker, "cb", None), "state", None) or "unknown",
        })

    @app.get("/metrics", tags=["infra"])
    async def metrics():
        # отдаём уже собранные пром-метрики отдачей plain text (если экспортер внутри utils.metrics)
        # либо заглушка
        try:
            from crypto_ai_bot.utils.metrics import export_prometheus  # type: ignore
            payload = export_prometheus()
            return PlainTextResponse(payload)
        except Exception:
            return PlainTextResponse("# no metrics exporter wired\n")

    @app.post("/telegram/webhook", tags=["adapters"])
    async def telegram_webhook(request: Request):
        body = await request.body()
        c = app.state.container
        # Новый вариант (рекомендуется): tg_handle(container, payload)
        # return await tg_handle(c, body)  # <- раскомментируйте, если уже перешли на новую сигнатуру

        # Легаси вариант (оставлен для совместимости): tg_handle_legacy(app, body, container)
        if tg_handle_legacy:
            return await tg_handle_legacy(app, body, c)
        return JSONResponse({"ok": False, "error": "telegram_handler_not_configured"}, status_code=500)

    return app


app = create_app()
