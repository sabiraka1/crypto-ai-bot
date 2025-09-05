from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

# ВАЖНО: импортируем compose() и даём локальный алиас,
# чтобы не менять остальной код:
from crypto_ai_bot.app.compose import compose as build_container_async  # совместимо с compose.py

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc, hist, export_text

logger = get_logger(__name__)


# ---------------- Rate Limiter (простой in-memory) ----------------

class RateLimiter:
    def __init__(self, limit: int = 60, window_sec: int = 60, max_keys: int = 10_000) -> None:
        self.limit = int(limit)
        self.window = float(window_sec)
        self.max_keys = int(max_keys)
        # key -> (window_start_ts, count)
        self.bucket: Dict[str, tuple[float, int]] = {}

    def _key(self, request: Request) -> str:
        # Ключ на основе IP + Authorization (если есть)
        ip = request.client.host if request.client else "unknown"
        auth = request.headers.get("authorization", "")
        return f"{ip}|{auth}"

    def allow(self, request: Request) -> bool:
        now = time.monotonic()
        key = self._key(request)
        win_start, count = self.bucket.get(key, (now, 0))

        if now - win_start >= self.window:
            # новый окно
            self.bucket[key] = (now, 1)
            # простая «обрезка» карты, чтобы не росла бесконечно
            if len(self.bucket) > self.max_keys:
                # удаляем произвольный старый элемент
                self.bucket.pop(next(iter(self.bucket)))
            return True

        if count < self.limit:
            self.bucket[key] = (win_start, count + 1)
            return True

        return False


rl = RateLimiter(limit=120, window_sec=60)


# ---------------- FastAPI app + lifespan ----------------

app = FastAPI(title="crypto-ai-bot API")


@app.on_event("startup")
async def _startup() -> None:
    """
    Загружаем DI-контейнер и стартуем ключевые компоненты.
    Делаем это аккуратно и идемпотентно.
    """
    # Сохраняем контейнер в app.state
    container = await build_container_async()
    app.state.container = container

    # Явно стартуем event bus и health (не полагаясь на AppContainer.start)
    await container.bus.start()
    await container.health.start()

    # DMS — если включен
    if getattr(container.settings, "DMS_ENABLED", False):
        try:
            await container.dms.start()
        except Exception:  # устойчиво
            logger.error("dms.start_failed", exc_info=True)

    # Защитные выходы: стартуем по каждому символу оркестратора
    try:
        for sym in container.orchestrators.keys():
            try:
                await container.exits.start(sym)  # наша ProtectiveExits ожидает symbol
            except Exception:
                logger.error("exits.start_failed", extra={"symbol": sym}, exc_info=True)
    except Exception:
        # если защитные выходы не критичны — не валим приложение
        logger.error("exits.bulk_start_failed", exc_info=True)

    # Автостарт оркестраторов если задано
    if getattr(container.settings, "AUTOSTART", False):
        for sym, orch in container.orchestrators.items():
            try:
                await orch.start()
                logger.info("orchestrator.autostart", extra={"symbol": sym})
            except Exception:
                logger.error("orchestrator.autostart_failed", extra={"symbol": sym}, exc_info=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    """Корректно останавливаем все компоненты."""
    container = getattr(app.state, "container", None)
    if container is None:
        return

    # Оркестраторы
    for sym, orch in container.orchestrators.items():
        with contextlib.suppress(Exception):
            await orch.stop()

    # Остальные компоненты
    with contextlib.suppress(Exception):
        await container.exits.stop()
    with contextlib.suppress(Exception):
        await container.health.stop()
    with contextlib.suppress(Exception):
        await container.dms.stop()
    with contextlib.suppress(Exception):
        await container.bus.stop()

    # Лок на инстанс
    with contextlib.suppress(Exception):
        container.instance_lock.release()


# ---------------- Метрики и middleware ----------------

@app.middleware("http")
async def _metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    # Используем шаблон пути (route.path), а не конкретный URL —
    # так мы понижаем кардинальность лейблов в Prometheus.
    route = request.scope.get("route")
    path_template = getattr(route, "path", request.url.path)
    method = request.method

    h = hist("http_request_latency_seconds", path=path_template, method=method)
    # Если prometheus_client не установлен — h может быть None
    timer_cm = h.time() if hasattr(h, "time") else contextlib.nullcontext()

    with timer_cm:  # type: ignore[arg-type]
        try:
            response = await call_next(request)
        finally:
            inc("http_requests_total", path=path_template, method=method)

    return response


# ---------------- Рейткеп на write-эндпойнтах ----------------

async def _ensure_rate_limit(request: Request) -> None:
    if not rl.allow(request):
        inc("http_rate_limited_total")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


# ---------------- Базовые эндпоинты ----------------

@app.get("/health", response_class=JSONResponse)
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint() -> Response:
    # Выгрузка прометей-метрик
    return PlainTextResponse(export_text(), media_type="text/plain; version=0.0.4")


# ---------------- Управление оркестраторами ----------------

@app.post("/orchestrator/{symbol}/start")
async def start_orchestrator(symbol: str, request: Request) -> dict[str, Any]:
    await _ensure_rate_limit(request)
    container = app.state.container
    orch = container.orchestrators.get(symbol)
    if not orch:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")
    await orch.start()
    inc("orchestrator_start_total", symbol=symbol)
    return {"status": "started", "symbol": symbol}


@app.post("/orchestrator/{symbol}/stop")
async def stop_orchestrator(symbol: str, request: Request) -> dict[str, Any]:
    await _ensure_rate_limit(request)
    container = app.state.container
    orch = container.orchestrators.get(symbol)
    if not orch:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")
    await orch.stop()
    inc("orchestrator_stop_total", symbol=symbol)
    return {"status": "stopped", "symbol": symbol}


@app.get("/orchestrator/{symbol}/status", response_class=JSONResponse)
async def orchestrator_status(symbol: str) -> dict[str, Any]:
    container = app.state.container
    orch = container.orchestrators.get(symbol)
    if not orch:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")
    # Минимальный статус (можно расширить из самого Orchestrator)
    return {
        "symbol": symbol,
        "running": getattr(orch, "is_running", lambda: False)(),
    }


# ---------------- Управление ProtectiveExits (по желанию) ----------------

@app.post("/exits/{symbol}/start")
async def start_exits(symbol: str, request: Request) -> dict[str, Any]:
    await _ensure_rate_limit(request)
    container = app.state.container
    await container.exits.start(symbol)
    inc("exits_start_total", symbol=symbol)
    return {"status": "started", "symbol": symbol}


@app.post("/exits/{symbol}/stop")
async def stop_exits(symbol: str, request: Request) -> dict[str, Any]:
    await _ensure_rate_limit(request)
    container = app.state.container
    await container.exits.stop(symbol)
    inc("exits_stop_total", symbol=symbol)
    return {"status": "stopped", "symbol": symbol}
