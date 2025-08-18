# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse

# внутренняя сборка контейнера
from crypto_ai_bot.app.compose import build_container

# метрики и проверка рассинхрона времени с биржей
from crypto_ai_bot.utils.metrics import export as export_metrics
from crypto_ai_bot.utils.time_sync import measure_time_drift_ms

logger = logging.getLogger("app.server")

# Глобальный контейнер и пул фоновых задач
container: Any = None
_BG_TASKS: set[asyncio.Task] = set()


async def _housekeeping_loop(cont: Any) -> None:
    """
    Периодически чистим просроченные ключи идемпотентности и изредка оптимизируем SQLite.
    Запускается в фоне при старте приложения.
    """
    idem = getattr(cont, "idempotency_repo", None)
    con = getattr(cont, "con", None)
    while True:
        try:
            if idem is not None:
                ttl = int(getattr(cont.settings, "IDEMPOTENCY_TTL_SEC", 300))
                idem.cleanup_expired(ttl_seconds=ttl)
            if con is not None and random.random() < 0.1:
                con.execute("PRAGMA optimize")
        except Exception as e:
            # логируем и продолжаем цикл — это сервисная задача
            logger.exception("housekeeping error: %s", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global container
    # Старт: собираем контейнер и запускаем фоновую уборку
    try:
        container = build_container()
        logger.info("container built: mode=%s symbol=%s",
                    getattr(container.settings, "MODE", "paper"),
                    getattr(container.settings, "SYMBOL", "BTC/USDT"))
    except Exception as e:
        logger.exception("failed to build container: %s", e)
        raise

    hk_task = asyncio.create_task(_housekeeping_loop(container))
    _BG_TASKS.add(hk_task)
    try:
        yield
    finally:
        # Грейсфул остановка фоновых задач
        for t in list(_BG_TASKS):
            t.cancel()
        for t in list(_BG_TASKS):
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("background task termination error: %s", e)
        _BG_TASKS.clear()
        logger.info("server shutdown complete")


app = FastAPI(title="crypto-ai-bot", version="1.0", lifespan=lifespan)

# ----------------------------- #
#              API              #
# ----------------------------- #

@app.get("/metrics")
def metrics():
    """Prometheus-текст в формате 0.0.4."""
    return PlainTextResponse(export_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/health")
def health():
    """
    Расширенный health: broker/db/bus/time_sync.
    Статус:
      - healthy: все основные подсистемы ок (time_sync 'ok' или 'unknown')
      - degraded: часть подсистем ок, но есть предупреждения (например, time_sync 'degraded')
      - unhealthy: одна из критичных подсистем (broker|db|bus) не ок
    """
    cfg = container.settings

    # 1) broker
    try:
        t = container.broker.fetch_ticker(getattr(cfg, "SYMBOL", "BTC/USDT"))
        broker_ok = bool(t)
    except Exception as e:
        logger.warning("health: broker check failed: %s", e)
        broker_ok = False

    # 2) db
    try:
        row = container.con.execute("PRAGMA user_version").fetchone()
        db_ok = row is not None
    except Exception as e:
        logger.warning("health: db check failed: %s", e)
        db_ok = False

    # 3) bus
    try:
        bus_h = container.bus.health()
    except Exception as e:
        logger.warning("health: bus check failed: %s", e)
        bus_h = {"running": False, "dlq_size": None, "queue_size": None, "queue_cap": None}
    bus_ok = bool(bus_h.get("running", False))

    # 4) time-sync
    try:
        ts = measure_time_drift_ms(container.broker)
        max_drift = int(getattr(cfg, "MAX_TIME_DRIFT_MS", 5_000))
        ts_status = "ok" if ts.get("ok") and ts.get("drift_ms", 0) <= max_drift else "degraded"
    except Exception as e:
        logger.warning("health: time_sync check failed: %s", e)
        ts = {"ok": False, "drift_ms": 0, "source": "none"}
        ts_status = "unknown"

    status = "healthy" if (broker_ok and db_ok and bus_ok and ts_status in ("ok", "unknown")) else "degraded"
    if not (broker_ok and db_ok and bus_ok):
        status = "unhealthy"

    return {
        "status": status,
        "broker": {"ok": broker_ok},
        "db": {"ok": db_ok},
        "bus": {"ok": bus_ok, **bus_h},
        "time_sync": {"status": ts_status, **ts},
    }


@app.get("/status")
def status_basic():
    """Краткий статус бота (режим, символ, таймфрейм, профиль)."""
    s = container.settings
    return {
        "mode": getattr(s, "MODE", "paper"),
        "symbol": getattr(s, "SYMBOL", "BTC/USDT"),
        "timeframe": getattr(s, "TIMEFRAME", "1h"),
        "profile": getattr(s, "PROFILE", getattr(s, "ENV", "default")),
    }


@app.get("/status/extended")
def status_extended():
    """Расширенный статус: базовая информация + bus/заказы/БД."""
    s = container.settings
    try:
        pending = container.trades_repo.count_pending()
    except Exception:
        pending = None

    try:
        bus_h = container.bus.health()
    except Exception as e:
        logger.warning("status/extended: bus.health failed: %s", e)
        bus_h = {"running": False, "dlq_size": None, "queue_size": None, "queue_cap": None}

    try:
        row = container.con.execute("PRAGMA user_version").fetchone()
        db_user_version = int(row[0]) if row and row[0] is not None else None
    except Exception as e:
        logger.warning("status/extended: user_version failed: %s", e)
        db_user_version = None

    return {
        "mode": getattr(s, "MODE", "paper"),
        "symbol": getattr(s, "SYMBOL", "BTC/USDT"),
        "timeframe": getattr(s, "TIMEFRAME", "1h"),
        "profile": getattr(s, "PROFILE", getattr(s, "ENV", "default")),
        "bus": bus_h,
        "pending_orders": pending,
        "db": {"user_version": db_user_version},
    }


@app.post("/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    """
    Telegram webhook.
    Секрет (если задан) сверяется с заголовком X-Telegram-Bot-Api-Secret-Token.
    Тело запроса просто прокидываем в adapters.telegram.handle_update.
    """
    # проверка секрета (если настроен)
    secret = (
        getattr(container.settings, "TELEGRAM_BOT_SECRET", None)
        or getattr(container.settings, "TELEGRAM_SECRET", None)
        or getattr(container.settings, "TELEGRAM_API_SECRET", None)
    )
    if secret and x_telegram_bot_api_secret_token != secret:
        return JSONResponse({"status": "forbidden"}, status_code=403)

    body = await request.body()

    # динамический импорт обработчика — чтобы избежать циклов при старте
    from crypto_ai_bot.app.adapters.telegram import handle_update
    try:
        return await handle_update(app, body, container)
    except Exception as e:
        logger.exception("telegram handler failed: %s", e)
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
