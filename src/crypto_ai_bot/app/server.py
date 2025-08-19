# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.app.adapters.telegram import handle_update
from crypto_ai_bot.core.orchestrator import Orchestrator
from crypto_ai_bot.core.brokers.symbols import normalize_symbol

logger = logging.getLogger(__name__)

# --- optional middlewares (request_id + rate limit) ---
try:
    from crypto_ai_bot.app.middleware import RequestIdMiddleware, RateLimitMiddleware  # type: ignore
except Exception:
    RequestIdMiddleware = None
    RateLimitMiddleware = None


class RedactFilter(logging.Filter):
    KEYS = (
        "API_KEY",
        "API_SECRET",
        "TELEGRAM_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_SECRET",
        "GATEIO_KEY",
        "GATEIO_SECRET",
        "DB_URL",
    )
    RE = re.compile(r"(?i)\b(" + "|".join(re.escape(k) for k in KEYS) + r")\b\s*[:=]\s*([^\s,;]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = str(record.getMessage())
            masked = self.RE.sub(lambda m: f"{m.group(1)}=<redacted>", msg)
            if masked != msg:
                record.msg = masked
                record.args = ()
        except Exception:
            pass
        return True


def _install_redaction():
    logging.getLogger().addFilter(RedactFilter())


def _param_bool(v: Optional[str]) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


async def _check_ohlcv_gaps(broker: Any, symbol: str, timeframe: str, limit: int = 50) -> Dict[str, Any]:
    """
    Быстрая проверка качества данных: есть ли разрывы тайм-серии в последних N свечах.
    Мы не дергаем её по умолчанию (дорого по лимитам) — только когда ?deep=1.
    """
    try:
        if not hasattr(broker.ccxt, "fetch_ohlcv"):
            return {"ok": True, "checked": 0}
        rows = broker.ccxt.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit) or []
        if len(rows) < 3:
            return {"ok": True, "checked": len(rows)}
        step = rows[-1][0] - rows[-2][0]
        gaps = []
        for i in range(1, len(rows)):
            d = rows[i][0] - rows[i - 1][0]
            if step and d > step:
                gaps.append({"from": rows[i - 1][0], "to": rows[i][0], "missed_ms": int(d - step)})
        return {"ok": len(gaps) == 0, "checked": len(rows), "gaps": gaps}
    except Exception as e:
        return {"ok": False, "error": f"ohlcv_check_failed:{e!r}"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_redaction()
    container = build_container()
    app.state.container = container

    # Шину событий запускаем в lifespan, а не в compose.py
    if hasattr(container, "bus") and hasattr(container.bus, "start"):
        await container.bus.start()

    # Единый оркестратор всех фоновых задач
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
        # Корректная остановка: ждём завершение тик-тасков, затем шину
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
        # Закрываем подключения репозиториев/БД
        for name in ("trades_repo", "positions_repo", "exits_repo", "idempotency_repo", "storage", "db"):
            try:
                obj = getattr(container, name, None)
                if obj and hasattr(obj, "close"):
                    obj.close()
            except Exception:
                pass


def create_app() -> FastAPI:
    application = FastAPI(title="crypto-ai-bot", version="1.1", lifespan=lifespan)

    # Включаем middleware, если доступны
    if RequestIdMiddleware:
        application.add_middleware(RequestIdMiddleware)
    if RateLimitMiddleware:
        application.add_middleware(RateLimitMiddleware)

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
    async def health(deep: Optional[str] = None):
        """
        Базовые проверки всегда; «дорогие» — при ?deep=1.
        """
        c = application.state.container
        st = c.settings
        sym = normalize_symbol(getattr(st, "SYMBOL", "BTC/USDT"))
        timeframe = getattr(st, "TIMEFRAME", "15m")

        # --- heartbeat / snapshots от оркестратора ---
        try:
            snap = application.state.orchestrator.health_snapshot()
        except Exception:
            snap = {}

        # --- локальные позиции и баланс биржи (быстрая сверка) ---
        local_qty = 0.0
        try:
            if hasattr(c.positions_repo, "get_open"):
                rows = c.positions_repo.get_open() or []
                for r in rows:
                    if str(r.get("symbol")) == sym:
                        local_qty = float(r.get("qty") or 0.0)
                        break
        except Exception:
            pass

        exch_qty = None
        try:
            bal = c.broker.fetch_balance() or {}
            base = sym.split("/")[0] if "/" in sym else sym.split(":")[0]
            total = (bal.get("total") or {})
            if base in total:
                exch_qty = float(total.get(base) or 0.0)
            else:
                free = (bal.get("free") or {})
                used = (bal.get("used") or {})
                exch_qty = float(free.get(base, 0.0)) + float(used.get(base, 0.0))
        except Exception:
            exch_qty = None

        drift = None if exch_qty is None else abs(exch_qty - local_qty)

        # --- активные SL/TP ---
        exits_active = None
        try:
            if hasattr(c.exits_repo, "count_active"):
                exits_active = int(c.exits_repo.count_active(symbol=sym))
            elif hasattr(c.exits_repo, "list_active"):
                exits_active = len(c.exits_repo.list_active(symbol=sym) or [])
        except Exception:
            exits_active = None

        # --- latency до биржи (лёгкий ping, если снапшот пуст) ---
        last_latency_ms = snap.get("last_latency_ms")
        if last_latency_ms is None:
            try:
                t0 = time.time()
                _ = c.broker.fetch_ticker(sym)
                last_latency_ms = int((time.time() - t0) * 1000)
            except Exception:
                last_latency_ms = None

        # --- deep: проверка качества OHLCV ---
        deep_checks: Dict[str, Any] = {}
        if _param_bool(deep):
            deep_checks["ohlcv"] = await _check_ohlcv_gaps(c.broker, sym, timeframe=timeframe, limit=50)

        details: Dict[str, Any] = {
            "mode": getattr(st, "MODE", "paper"),
            "symbol": sym,
            "timeframe": timeframe,
            "heartbeat_ms": snap.get("heartbeat_ms"),
            "ticks": {
                "eval_ms": snap.get("last_eval_ms"),
                "exits_ms": snap.get("last_exits_ms"),
                "reconcile_ms": snap.get("last_reconcile_ms"),
                "balance_ms": snap.get("last_balance_ms"),
            },
            "latency_ms": last_latency_ms,
            "positions": {"local_qty": local_qty, "exchange_qty": exch_qty, "drift": drift},
            "exits_active": exits_active,
            "deep": deep_checks or None,
        }
        return JSONResponse({"ok": True, "details": details})

    @application.get("/metrics", tags=["meta"])
    async def metrics():
        # Отдаём registries из utils.metrics, если есть; иначе — простой fallback
        try:
            from crypto_ai_bot.utils import metrics as m  # type: ignore
            if hasattr(m, "export"):
                return PlainTextResponse(m.export())
        except Exception:
            pass
        c = application.state.container
        lines = []
        cb = getattr(getattr(c, "broker", None), "cb", None)
        if cb:
            s = cb.metrics()
            for k, v in s.items():
                if k == "errors_by_kind":
                    for kk, vv in (v or {}).items():
                        lines.append(f'cb_errors_by_kind{{kind="{kk}"}} {vv}')
                else:
                    lines.append(f"cb_{k} {v if v is not None else 0}")
        return PlainTextResponse("\n".join(lines) + "\n")

    @application.post("/telegram", tags=["adapters"])  # Убрали /webhook
    async def telegram_webhook(request: Request):
        body = await request.body()
        c = application.state.container
        # Совместимость со старой и новой сигнатурой хендлера:
        try:
            return await handle_update(c, body)                  # новая: (container, payload)
        except TypeError:
            return await handle_update(application, body, c)     # старая: (app, body, container)

    return application


app = create_app()
