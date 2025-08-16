# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, status

# --- Core / Utils imports (строго по правилам) ---
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers import create_broker, ExchangeInterface
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe
from crypto_ai_bot.app.adapters.telegram import handle_update
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.time_sync import measure_time_drift
from crypto_ai_bot.core.storage.sqlite_adapter import connect as sqlite_connect

# Никаких прямых импортов индикаторов/репозиториев/use_cases тут нет.


# ----------------------- Глобальный контекст приложения -----------------------

@dataclass
class AppCtx:
    cfg: Settings
    http: Any
    broker: ExchangeInterface
    symbol: str
    timeframe: str
    feature_limit: int

CTX: Optional[AppCtx] = None


def _build_ctx() -> AppCtx:
    cfg = Settings.build()
    http = get_http_client()
    # Нормализуем символ/таймфрейм один раз
    symbol = normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT"))
    timeframe = normalize_timeframe(getattr(cfg, "TIMEFRAME", "1h"))
    # создаём брокера через фабрику
    broker = create_broker(cfg)
    feature_limit = int(getattr(cfg, "FEATURE_LIMIT", 300))
    return AppCtx(cfg=cfg, http=http, broker=broker, symbol=symbol, timeframe=timeframe, feature_limit=feature_limit)


app = FastAPI(title="crypto-ai-bot", version=getattr(Settings, "APP_VERSION", "0.0.0"))


@app.on_event("startup")
async def on_startup() -> None:
    global CTX
    # Инициализацию делаем синхронной в отдельном треде, чтобы не блокировать event loop
    CTX = await asyncio.to_thread(_build_ctx)
    metrics.inc("app_startups_total", {"app": "crypto-ai-bot"})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if CTX and CTX.broker:
        try:
            CTX.broker.close()
        except Exception:
            pass


# --------------------------- Health helpers -----------------------------------

@dataclass
class ComponentStatus:
    ok: bool
    status: str           # "healthy" | "degraded" | "unhealthy" | "unknown"
    latency_ms: float
    detail: str = ""


async def _check_db(cfg: Settings) -> ComponentStatus:
    t0 = time.perf_counter()
    ok = False
    detail = ""
    try:
        def _probe() -> None:
            con = sqlite_connect(getattr(cfg, "DB_PATH", ":memory:"))
            try:
                cur = con.cursor()
                cur.execute("SELECT 1;")
                _ = cur.fetchone()
            finally:
                con.close()
        await asyncio.to_thread(_probe)
        ok = True
        status_s = "healthy"
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        status_s = "unhealthy"
    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.observe("health_check_duration_ms", latency_ms, {"component": "db"})
    return ComponentStatus(ok=ok, status=status_s, latency_ms=latency_ms, detail=detail)


async def _check_broker(broker: ExchangeInterface, symbol: str) -> ComponentStatus:
    t0 = time.perf_counter()
    ok = False
    detail = ""
    try:
        # сетевой вызов — вынесем в тред
        def _probe() -> None:
            _ = broker.fetch_ticker(symbol)
        await asyncio.to_thread(_probe)
        ok = True
        status_s = "healthy"
    except Exception as e:
        # любой сбой брокера считаем деградацией (приложение живо, но торговля недоступна)
        detail = f"{type(e).__name__}: {e}"
        status_s = "degraded"
    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.observe("health_check_duration_ms", latency_ms, {"component": "broker"})
    return ComponentStatus(ok=ok, status=status_s, latency_ms=latency_ms, detail=detail)


async def _check_bus() -> ComponentStatus:
    # Если в проекте есть core.events.get_bus(cfg) и health() — используй.
    # Иначе считаем шину "unknown" без ошибок.
    t0 = time.perf_counter()
    detail = "not_implemented"
    status_s = "unknown"
    ok = True
    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.observe("health_check_duration_ms", latency_ms, {"component": "bus"})
    return ComponentStatus(ok=ok, status=status_s, latency_ms=latency_ms, detail=detail)


async def _check_time_sync(http) -> ComponentStatus:
    t0 = time.perf_counter()
    try:
        drift_ms = await measure_time_drift(http)  # может вернуть None, если недоступно
        latency_ms = (time.perf_counter() - t0) * 1000.0
        metrics.observe("health_check_duration_ms", latency_ms, {"component": "time"})
        if drift_ms is None:
            return ComponentStatus(ok=True, status="unknown", latency_ms=latency_ms, detail="no_external_time")
        # Порог дрейфа задаём через Settings или дефолт
        max_drift_ms = getattr(CTX.cfg, "MAX_TIME_DRIFT_MS", 1000)
        if abs(drift_ms) > max_drift_ms:
            return ComponentStatus(ok=False, status="unhealthy", latency_ms=latency_ms, detail=f"drift_ms={drift_ms}")
        return ComponentStatus(ok=True, status="healthy", latency_ms=latency_ms, detail=f"drift_ms={drift_ms}")
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        metrics.observe("health_check_duration_ms", latency_ms, {"component": "time"})
        return ComponentStatus(ok=True, status="unknown", latency_ms=latency_ms, detail=f"error:{e}")


def _overall_status(components: Dict[str, ComponentStatus]) -> str:
    # матрица: если БД плоха → unhealthy; если брокер плох (degraded) → degraded; иначе healthy/unknown
    if components["db"].status == "unhealthy":
        return "unhealthy"
    if components["broker"].status in ("degraded", "unhealthy"):
        return "degraded"
    # time/bus могут быть unknown и не влияют на основной статус
    return "healthy"


# --------------------------------- Routes -------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    if CTX is None:
        return {"ok": False, "status": "unhealthy", "reason": "ctx_not_ready"}

    db = await _check_db(CTX.cfg)
    broker = await _check_broker(CTX.broker, CTX.symbol)
    bus = await _check_bus()
    timecmp = await _check_time_sync(CTX.http)

    components = {
        "db": asdict(db),
        "broker": asdict(broker),
        "bus": asdict(bus),
        "time": asdict(timecmp),
    }
    overall = _overall_status({"db": db, "broker": broker, "bus": bus, "time": timecmp})

    resp = {
        "ok": overall == "healthy",
        "status": overall,
        "mode": getattr(CTX.cfg, "MODE", "paper"),
        "version": getattr(Settings, "APP_VERSION", "0.0.0"),
        "components": components,
        "defaults": {"symbol": CTX.symbol, "timeframe": CTX.timeframe},
    }
    return resp


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    data = metrics.export()
    return Response(content=data, media_type="text/plain; version=0.0.4")


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Dict[str, Any]:
    if CTX is None:
        return {"ok": False, "error": "ctx_not_ready"}

    # Проверка секрета до чтения тела
    secret_cfg = getattr(CTX.cfg, "TELEGRAM_WEBHOOK_SECRET", None)
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_cfg:
        if secret_hdr is None or secret_hdr != secret_cfg:
            return {"ok": False, "error": "forbidden"}, status.HTTP_403_FORBIDDEN

    update = await request.json()
    # создаём простой «бот-обёртку» вокруг use_cases:
    class _BotFacade:
        def __init__(self, ctx: AppCtx) -> None:
            self.ctx = ctx

        def evaluate(self, *, symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
            # тонкая обёртка — вместо импорта use_cases здесь
            from crypto_ai_bot.core.signals.policy import decide
            return decide(self.ctx.cfg, self.ctx.broker, symbol=symbol, timeframe=timeframe, limit=limit)

        def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
            # полноценное исполнение обычно идёт через use_cases; оставим простую заглушку
            from crypto_ai_bot.core.use_cases.place_order import place_order
            return place_order(self.ctx.cfg, self.ctx.broker, self.ctx.repos, decision)  # если у тебя repos в CTX

    # Если у тебя репозитории инициализируются отдельно — добавь в CTX.repos и используй
    bot = _BotFacade(CTX)
    result = await handle_update(update, CTX.cfg, bot, CTX.http)
    return {"ok": True, **result}
