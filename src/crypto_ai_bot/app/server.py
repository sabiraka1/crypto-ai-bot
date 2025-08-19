# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse

# --- middleware (опционально; если файла нет — просто пропустим) ---
try:
    from crypto_ai_bot.app.middleware import RateLimitMiddleware  # noqa: F401
    _HAS_RLMW = True
except Exception:
    _HAS_RLMW = False

# --- контейнер и составление зависимостей ---
from crypto_ai_bot.app.compose import build_container  # ваша фабрика контейнера

# --- метрики ---
from crypto_ai_bot.utils import metrics
# в utils.metrics экспортёр называется export()
from crypto_ai_bot.utils.metrics import export as export_metrics

# --- телеграм-адаптер (делегируем обработку апдейтов) ---
try:
    from crypto_ai_bot.app.adapters.telegram import handle_update as telegram_handle_update
except Exception:
    telegram_handle_update = None  # graceful fallback

logger = logging.getLogger("server")


async def _housekeeping_loop(container: Any) -> None:
    """
    Периодическая «домработа»: тик защитных выходов, очистка идемпотентности,
    необязательная оптимизация БД. Любая ошибка — в лог + метрика.
    """
    idem = getattr(container, "idempotency_repo", None)
    exits = getattr(container, "exits_repo", None)
    con = getattr(container, "con", None)
    interval = float(getattr(container.settings, "HOUSEKEEPING_INTERVAL_SEC", 60.0))

    while True:
        try:
            # 1) защитные выходы (если есть)
            if exits is not None and hasattr(exits, "tick"):
                exits.tick()

            # 2) очистка идемпотентности
            if idem is not None and hasattr(idem, "cleanup_expired"):
                ttl = int(getattr(container.settings, "IDEMPOTENCY_TTL_SEC", 300))
                deleted = idem.cleanup_expired(ttl_seconds=ttl)
                if deleted:
                    logger.info("housekeeping: idempotency deleted=%s", deleted)

            # 3) периодическая оптимизация SQLite (опционально)
            if con is not None:
                con.execute("PRAGMA optimize")

        except asyncio.CancelledError:
            # штатное завершение фоновой задачи
            break
        except Exception:
            # ВАЖНО: не глушим — пишем стектрейс и инкрементим метрику
            logger.exception("housekeeping tick failed")
            metrics.inc("housekeeping_tick_failures_total", value=1.0)
        finally:
            await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Инициализация контейнера, запуск bus/housekeeping, корректное завершение.
    """
    container = build_container()
    app.state.container = container

    # стартуем EventBus (если есть оболочка bus с .start/.stop)
    bus = getattr(container, "bus", None)
    if bus is not None and hasattr(bus, "start"):
        try:
            await bus.start()
        except Exception:
            logger.exception("bus start failed")

    # фоновая «домработа»
    hk_task = asyncio.create_task(_housekeeping_loop(container), name="housekeeping")

    try:
        yield
    finally:
        # graceful shutdown housekeeping
        hk_task.cancel()
        try:
            await hk_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("housekeeping join failed")

        # останавливаем bus
        if bus is not None and hasattr(bus, "stop"):
            try:
                await bus.stop()
            except Exception:
                logger.exception("bus stop failed")

        # закрываем соединения БД (если требуется)
        con = getattr(container, "con", None)
        if con is not None:
            try:
                con.close()
            except Exception:
                logger.exception("db close failed")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # rate limit middleware (если присутствует в проекте)
    if _HAS_RLMW:
        app.add_middleware(RateLimitMiddleware, global_rps=20.0)

    @app.get("/health")
    async def health() -> JSONResponse:
        """
        Лёгкий health с базовой информацией и CB-статами брокера.
        Без синхронных сетевых вызовов.
        """
        cont = app.state.container
        cfg = cont.settings

        broker = getattr(cont, "broker", None)
        cb_stats: Optional[dict] = None
        if broker is not None and hasattr(broker, "cb"):
            try:
                cb_stats = broker.cb.get_stats()  # utils.circuit_breaker
            except Exception:
                logger.debug("health: cb.get_stats failed", exc_info=True)
                cb_stats = None

        bus = getattr(cont, "bus", None)
        bus_health = None
        if bus is not None and hasattr(bus, "health"):
            try:
                bus_health = bus.health()
            except Exception:
                logger.debug("health: bus.health failed", exc_info=True)

        return JSONResponse(
            {
                "ok": True,
                "mode": getattr(cfg, "MODE", "paper"),
                "exchange": getattr(cfg, "EXCHANGE", "binance"),
                "symbol": getattr(cfg, "SYMBOL", "BTC/USDT"),
                "timeframe": getattr(cfg, "TIMEFRAME", "1h"),
                "broker_circuit_breaker": cb_stats,
                "bus": bus_health,
            }
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(export_metrics(), media_type="text/plain; version=0.0.4")

    @app.get("/status")
    async def status() -> JSONResponse:
        """
        Расширенный статус по открытым позициям и idempotency.
        Работает быстро и без блокировки event loop.
        """
        cont = app.state.container
        positions_repo = getattr(cont, "positions_repo", None)

        open_positions = []
        try:
            if positions_repo is not None:
                open_positions = positions_repo.get_open()
        except Exception:
            logger.exception("status: positions_repo.get_open failed")

        idem_repo = getattr(cont, "idempotency_repo", None)
        idem_size = None
        try:
            if idem_repo is not None and hasattr(idem_repo, "approx_size"):
                idem_size = idem_repo.approx_size()
        except Exception:
            logger.debug("status: idempotency approx_size failed", exc_info=True)

        return JSONResponse(
            {
                "open_positions": open_positions,
                "idempotency_size": idem_size,
            }
        )

    @app.post("/telegram")
    async def telegram(
        request: Request,
        x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
    ) -> JSONResponse:
        """
        Простой webhook хендлер. Секрет — через заголовок (если задан в конфиге).
        Делегируем обработку в adapters.telegram.handle_update, если он есть.
        """
        cont = app.state.container
        secret = getattr(cont.settings, "TELEGRAM_BOT_SECRET", None)
        if secret and x_telegram_bot_api_secret_token != secret:
            return JSONResponse({"status": "forbidden"}, status_code=403)

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"status": "bad_request"}, status_code=400)

        if telegram_handle_update is None:
            # адаптер не подключён — просто «эхаем»
            return JSONResponse({"status": "ok", "echo": payload})

        try:
            # делегируем
            out = await telegram_handle_update(cont, payload)
            return JSONResponse(out or {"status": "ok"})
        except Exception:
            logger.exception("telegram handler failed")
            return JSONResponse({"status": "error"}, status_code=500)

    # простой «smoke» для проверки, что сервер жив
    @app.get("/test")
    async def test() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


# Gunicorn/Uvicorn entrypoint
app = create_app()
