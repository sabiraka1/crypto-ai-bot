# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import asyncio
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, status

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations.runner import apply_all
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client

# опционально: event bus health, если модуль есть
try:
    from crypto_ai_bot.core.events.bus import Bus  # type: ignore
except Exception:
    Bus = None  # type: ignore

# Telegram адаптер (тонкий)
from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle_update


# ------------------------------- вспомогательные -------------------------------

@dataclass
class AppState:
    cfg: Settings
    orchestrator: Orchestrator
    con: Any
    bot: Any
    http: Any
    bus: Any | None = None


def _make_bot(cfg: Settings, orch: Orchestrator, con: Any) -> Any:
    """
    Адаптация к разным вариантам core.bot:
      - get_bot(cfg, broker, con) → объект с evaluate/execute/get_status
      - Bot(cfg=..., broker=..., con=...)
      - иначе — безопасная заглушка
    """
    try:
        import importlib
        mod = importlib.import_module("crypto_ai_bot.core.bot")
        if hasattr(mod, "get_bot"):
            return mod.get_bot(cfg=cfg, broker=orch.broker, con=con)  # type: ignore
        if hasattr(mod, "Bot"):
            return getattr(mod, "Bot")(cfg=cfg, broker=orch.broker, con=con)  # type: ignore
    except Exception:
        pass

    # безопасная заглушка, чтобы не падать: всегда hold
    dummy = types.SimpleNamespace()
    dummy.evaluate = lambda **kw: {"action": "hold", "score": 0.5, "explain": {"risk": {"ok": True, "reason": "noop"}}}
    dummy.execute = lambda decision: {"status": "noop", "decision": decision}
    dummy.get_status = lambda: {"ok": True, "mode": getattr(cfg, "MODE", "unknown")}
    return dummy


async def _check_db_health(con) -> dict:
    try:
        cur = con.execute("SELECT 1;")
        _ = cur.fetchone()
        metrics.inc("health_checks_total", {"component": "db", "result": "ok"})
        return {"ok": True}
    except Exception as e:
        metrics.inc("health_checks_total", {"component": "db", "result": "err"})
        return {"ok": False, "error": repr(e)}


async def _check_broker_health(orch: Orchestrator, cfg: Settings) -> dict:
    # очень короткая проверка тика; не блокируем event-loop
    symbol = getattr(cfg, "HEALTHCHECK_SYMBOL", None) or getattr(cfg, "SYMBOL", "BTC/USDT")
    try:
        async def _job():
            return await asyncio.to_thread(orch.broker.fetch_ticker, symbol)
        res = await asyncio.wait_for(_job(), timeout=float(getattr(cfg, "HEALTHCHECK_TIMEOUT_SEC", 2.0)))
        if not isinstance(res, dict):
            raise RuntimeError("ticker shape")
        metrics.inc("health_checks_total", {"component": "broker", "result": "ok"})
        return {"ok": True, "price": res.get("last") or res.get("close") or res.get("price")}
    except Exception as e:
        metrics.inc("health_checks_total", {"component": "broker", "result": "err"})
        return {"ok": False, "error": repr(e)}


async def _check_bus_health(bus) -> dict:
    if bus is None:
        return {"ok": True, "note": "no-bus"}
    try:
        if hasattr(bus, "health"):
            res = await asyncio.to_thread(bus.health)
            metrics.inc("health_checks_total", {"component": "bus", "result": "ok"})
            return {"ok": True, "details": res}
        metrics.inc("health_checks_total", {"component": "bus", "result": "ok"})
        return {"ok": True}
    except Exception as e:
        metrics.inc("health_checks_total", {"component": "bus", "result": "err"})
        return {"ok": False, "error": repr(e)}


# ------------------------------- lifespan (startup/shutdown) -------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) конфиг
    cfg = Settings.build()

    # 2) база + миграции
    con = connect(getattr(cfg, "DB_PATH", "data/bot.sqlite3"))
    try:
        apply_all(con)
    except Exception as e:
        # не падаем — отметим деградацию; health покажет ошибку
        metrics.inc("migrations_failed_total", {})
        app.state.migrations_error = repr(e)

    # 3) оркестратор (внутри него уже включено плановое обслуживание БД)
    orch = Orchestrator(cfg)

    # 4) event bus (если есть)
    bus = None
    try:
        if Bus is not None:
            bus = Bus()
    except Exception:
        bus = None

    # 5) bot-фасад + http-клиент
    bot = _make_bot(cfg, orch, con)
    http = get_http_client()

    # 6) сохранить состояние
    app.state.state = AppState(cfg=cfg, orchestrator=orch, con=con, bot=bot, http=http, bus=bus)

    # 7) старт планировщика
    await orch.start()
    metrics.inc("app_start_total", {})
    try:
        yield
    finally:
        # аккуратный shutdown
        try:
            await orch.stop()
        except Exception:
            pass
        try:
            con.close()
        except Exception:
            pass
        metrics.inc("app_stop_total", {})


app = FastAPI(title="Crypto AI Bot", version="v1", lifespan=lifespan)


# ------------------------------- маршруты -------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    st: AppState = app.state.state  # type: ignore

    db = await _check_db_health(st.con)
    br = await _check_broker_health(st.orchestrator, st.cfg)
    bs = await _check_bus_health(st.bus)

    components = {"db": db, "broker": br, "bus": bs}
    ok_count = sum(1 for v in components.values() if v.get("ok"))
    if ok_count == len(components):
        status_str = "healthy"
    elif components["db"].get("ok"):
        status_str = "degraded"
    else:
        status_str = "unhealthy"

    return {
        "status": status_str,
        "components": components,
        "mode": getattr(st.cfg, "MODE", "unknown"),
        "version": app.version,
        "migrations_error": getattr(app.state, "migrations_error", None),
    }


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    text = metrics.export()
    return Response(content=text, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/telegram")
async def telegram_webhook(request: Request) -> Dict[str, Any]:
    st: AppState = app.state.state  # type: ignore
    # Секрет должен прийти до парсинга тела
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected = getattr(st.cfg, "TELEGRAM_WEBHOOK_SECRET", None)
    if expected and secret != expected:
        return {"ok": False, "error": "forbidden"}, status.HTTP_403_FORBIDDEN  # FastAPI сам проставит 200, поэтому вернём dict

    update = await request.json()
    # делегируем адаптеру
    reply = await tg_handle_update(update, st.cfg, st.bot, st.http)
    return {"ok": True, "reply": reply}
