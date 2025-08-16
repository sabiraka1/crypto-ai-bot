# src/crypto_ai_bot/app/server.py
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.utils import metrics

# опционально: синхронизация времени, если модуль есть
try:
    from crypto_ai_bot.utils import time_sync  # type: ignore
except Exception:
    time_sync = None  # type: ignore


app = FastAPI(title="Crypto AI Bot", version="v1")


# -------------------- lifecycle --------------------
@app.on_event("startup")
def _startup() -> None:
    cfg = Settings.build()
    app.state.cfg = cfg
    app.state.mode = getattr(cfg, "MODE", "paper")

    # брокер (через фабрику)
    app.state.broker = create_broker(cfg)
    metrics.inc("app_start_total", {"mode": app.state.mode})

    # попытка провязать хранилище и идемпотентность
    _wire_storage_and_idempotency(app)


def _wire_storage_and_idempotency(app: FastAPI) -> None:
    """
    Пытаемся подключить SQLite + репозитории + идемпотентность.
    Если чего-то нет — не падаем, просто оставляем evaluate-only.
    """
    cfg = app.state.cfg
    data_ok = False

    try:
        # 1) подключение к базе
        from crypto_ai_bot.core.storage.sqlite_adapter import connect  # type: ignore
        con_path = Path(getattr(cfg, "DB_PATH", "data/bot.db"))
        con_path.parent.mkdir(parents=True, exist_ok=True)
        con = connect(str(con_path))

        # 2) миграции (если есть)
        try:
            from crypto_ai_bot.core.storage.migrations.runner import apply_all  # type: ignore
            apply_all(con)
        except Exception:
            # мигратора нет — продолжаем без него
            pass

        # 3) репозитории
        from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository  # type: ignore
        from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository  # type: ignore
        from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository  # type: ignore

        trades_repo = SqliteTradeRepository(con)
        positions_repo = SqlitePositionRepository(con)
        audit_repo = SqliteAuditRepository(con)

        # 4) unit-of-work (если есть готовый)
        uow = None
        try:
            from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork  # type: ignore
            uow = SqliteUnitOfWork(con)
        except Exception:
            # fallback: примитивная обёртка
            class _UOW:
                def __init__(self, _con): self._con = _con
                def begin(self): self._con.execute("BEGIN IMMEDIATE")
                def commit(self): self._con.commit()
                def rollback(self): self._con.rollback()
            uow = _UOW(con)

        # 5) идемпотентность (если есть)
        idem_repo = None
        try:
            from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository  # type: ignore
            idem_repo = SqliteIdempotencyRepository(con)
        except Exception:
            idem_repo = None  # опционально

        # сохраним в состоянии приложения
        app.state.repos = {
            "trades": trades_repo,
            "positions": positions_repo,
            "audit": audit_repo,
        }
        app.state.uow = uow
        app.state.idempotency = idem_repo
        data_ok = True
    except Exception as e:
        # нет БД/репозиториев — продолжаем в evaluate-only
        app.state.repos = None
        app.state.uow = None
        app.state.idempotency = None

    metrics.inc("storage_wired_total", {"status": "ok" if data_ok else "skipped"})


def _ok(x: bool) -> str:
    return "ok" if x else "error"


# -------------------- health --------------------
@app.get("/health")
def health() -> JSONResponse:
    cfg = app.state.cfg
    broker = app.state.broker

    components: Dict[str, Dict[str, Any]] = {"mode": app.state.mode}
    status = "healthy"
    degradation = "none"

    # DB ping (если подключена)
    t0 = time.perf_counter()
    db_ok = True
    try:
        if app.state.repos is not None:
            # быстрая проверка транзакции
            app.state.uow.begin()
            app.state.uow.rollback()
    except Exception:
        db_ok = False
        status = "degraded"
        degradation = "major"
    db_latency = int((time.perf_counter() - t0) * 1000)
    components["db"] = {"status": _ok(db_ok), "latency_ms": db_latency}

    # broker ping
    try:
        t0 = time.perf_counter()
        _ = broker.fetch_ticker(getattr(cfg, "SYMBOL", "BTC/USDT"))
        br_lat = int((time.perf_counter() - t0) * 1000)
        components["broker"] = {"status": "ok", "latency_ms": br_lat}
    except Exception as e:
        status = "degraded"
        degradation = "major"
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e), "latency_ms": 0}

    # time drift (если есть модуль)
    if time_sync and hasattr(time_sync, "get_cached_drift_ms"):
        try:
            drift_ms = int(time_sync.get_cached_drift_ms(default=0))
            limit = int(getattr(cfg, "TIME_DRIFT_MAX_MS", 1500))
            drift_ok = drift_ms <= limit
            components["time"] = {"status": _ok(drift_ok), "drift_ms": drift_ms, "limit_ms": limit}
            if not drift_ok:
                status = "degraded"
                degradation = "major"
        except Exception as e:
            components["time"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    return JSONResponse({"status": status, "degradation_level": degradation, "components": components})


# -------------------- metrics --------------------
@app.get("/metrics")
def metrics_export() -> PlainTextResponse:
    return PlainTextResponse(metrics.export(), media_type="text/plain; version=0.0.4")


# -------------------- tick (evaluate + optional execute) --------------------
@app.post("/tick")
async def tick(request: Request) -> JSONResponse:
    """
    - Если БД/репозиториев нет или ENABLE_TRADING=false → только EVALUATE.
    - Если всё провязано и включено → EVAL_AND_EXECUTE с идемпотентностью.
    - Любые исключения переводим в JSON-ответ с status="error" (HTTP 200).
    """
    cfg = app.state.cfg
    broker = app.state.broker
    enable_trading = bool(getattr(cfg, "ENABLE_TRADING", False))

    try:
        payload = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = {}

    symbol = payload.get("symbol") if isinstance(payload, dict) else None
    timeframe = payload.get("timeframe") if isinstance(payload, dict) else None
    limit = payload.get("limit") if isinstance(payload, dict) else None

    # импортируем тут, чтобы избежать циклов при старте
    try:
        from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
    except Exception as e:
        body = {"status": "error", "error": f"import_failed: {type(e).__name__}: {e}"}
        return JSONResponse(jsonable_encoder(body))

    # evaluate-only режим (нет БД/репозиториев или выключено торговое исполнение)
    if not (enable_trading and app.state.repos and app.state.uow):
        try:
            result = uc_eval_and_execute(
                cfg,
                broker,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                positions_repo=None,
                trades_repo=None,
                audit_repo=None,
                uow=None,
                idempotency_repo=None,
            )
            return JSONResponse(jsonable_encoder(result))
        except Exception as e:
            body = {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}
            return JSONResponse(jsonable_encoder(body))

    # полный режим: с БД/идемпотентностью
    try:
        repos = app.state.repos
        result = uc_eval_and_execute(
            cfg,
            broker,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            positions_repo=repos["positions"],
            trades_repo=repos["trades"],
            audit_repo=repos["audit"],
            uow=app.state.uow,
            idempotency_repo=app.state.idempotency,
        )
        return JSONResponse(jsonable_encoder(result))
    except Exception as e:
        body = {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}
        return JSONResponse(jsonable_encoder(body))
