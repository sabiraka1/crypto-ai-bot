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

try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_legacy
except Exception:
    tg_handle_legacy = None

logger = logging.getLogger("app.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # build DI
        container = build_container()
        if container is None:
            raise RuntimeError("Failed to build container")
            
        app.state.container = container
        
        # EventBus
        if hasattr(container, "bus") and hasattr(container.bus, "start"):
            await container.bus.start()
        
        # Orchestrator
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
        
        yield
        
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise
        
    finally:
        # graceful shutdown
        try:
            if hasattr(app.state, "orchestrator"):
                await app.state.orchestrator.stop()
        except Exception:
            pass
        try:
            if hasattr(app.state.container, "bus") and hasattr(app.state.container.bus, "stop"):
                await app.state.container.bus.stop()
        except Exception:
            pass
        # закрываем репозитории/соединения
        if hasattr(app.state, "container"):
            container = app.state.container
            for name in ("trades_repo", "positions_repo", "exits_repo", "idempotency_repo", "con"):
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
        latency = 0.0
        try:
            # не блокируем loop
            t0 = time.time()
            tk = await asyncio.to_thread(c.broker.fetch_ticker, getattr(c.settings, "SYMBOL", "BTC/USDT"))
            latency = (time.time() - t0) * 1000  # в миллисекундах
            broker_ok = bool(tk)
        except Exception:
            broker_ok = False

        return JSONResponse({
            "ok": broker_ok,
            "exchange_latency_ms": latency,
            "mode": getattr(c.settings, "MODE", "unknown"),
        })

    @app.get("/metrics", tags=["infra"])
    async def metrics():
        try:
            from crypto_ai_bot.utils.metrics import export_prometheus
            payload = export_prometheus()
            return PlainTextResponse(payload)
        except Exception:
            return PlainTextResponse("# no metrics exporter wired\n")

    @app.post("/telegram", tags=["adapters"])  # Изменено с /telegram/webhook
    async def telegram_webhook(request: Request):
        body = await request.body()
        c = app.state.container
        
        if tg_handle_legacy:
            return await tg_handle_legacy(app, body, c)
        return JSONResponse({"ok": False, "error": "telegram_handler_not_configured"}, status_code=500)

    return app


app = create_app()