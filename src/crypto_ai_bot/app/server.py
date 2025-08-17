from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

# --- core/config ---
from crypto_ai_bot.core.settings import Settings

# --- storage / migrations / repos ---
from crypto_ai_bot.core.storage.sqlite_adapter import connect
try:
    # если есть раннер миграций — используем
    from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations
except Exception:  # pragma: no cover
    apply_migrations = None  # мягкая деградация

from crypto_ai_bot.core.storage.repositories import (
    SqliteTradeRepository,
    SqlitePositionRepository,
    SqliteSnapshotRepository,
    SqliteAuditRepository,
    SqliteIdempotencyRepository,
    SqliteDecisionsRepository,  # <-- новый репозиторий решений
)

# --- broker factory ---
# по нашей архитектуре фабрика — в base.py и реэкспортируется в __init__ (но импорт из base надёжнее)
from crypto_ai_bot.core.brokers.base import create_broker

# --- use-cases ---
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

# --- metrics / logging / time sync ---
from crypto_ai_bot.utils.metrics import inc, observe, export as metrics_export
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift  # если внедрён ранее
except Exception:  # pragma: no cover
    def measure_time_drift(urls: Optional[list[str]] = None, timeout: float = 1.0) -> int:
        return 0


# =========================
#   РЕПОЗИТОРИИ: сборка
# =========================
@dataclass
class Repos:
    trades: Any
    positions: Any
    snapshots: Any
    audit: Any
    idempotency: Any
    decisions: Optional[Any] = None
    uow: Optional[Any] = None  # если будет UnitOfWork — подставим

def _build_repos(con: sqlite3.Connection) -> Repos:
    return Repos(
        trades=SqliteTradeRepository(con),
        positions=SqlitePositionRepository(con),
        snapshots=SqliteSnapshotRepository(con),
        audit=SqliteAuditRepository(con),
        idempotency=SqliteIdempotencyRepository(con),
        decisions=SqliteDecisionsRepository(con),  # <-- ВАЖНО: тут подключаем репозиторий решений
        uow=None,
    )


# =========================
#     FASTAPI APP
# =========================
app = FastAPI(title="crypto-ai-bot")

@app.on_event("startup")
def on_startup() -> None:
    cfg = Settings.build()
    app.state.cfg = cfg

    # соединение с БД
    con = connect(cfg.DB_PATH)
    app.state.con = con

    # миграции (если есть раннер)
    if apply_migrations is not None:
        try:
            apply_migrations(con)
        except Exception as e:  # pragma: no cover
            # не падаем — возвращаем 'degraded' в /health
            app.state.migration_error = str(e)

    # сборка репозиториев
    app.state.repos = _build_repos(con)

    # брокер через фабрику
    broker = create_broker(mode=cfg.MODE, settings=cfg, http_client=None)
    app.state.broker = broker

    inc("app_start_total", {"mode": cfg.MODE})


# ---------- MODELS ----------
class TickIn(BaseModel):
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    limit: Optional[int] = None


# =========================
#        ENDPOINTS
# =========================
@app.get("/health")
def health() -> dict:
    cfg: Settings = app.state.cfg
    con: sqlite3.Connection = app.state.con
    broker = app.state.broker

    components = {"mode": cfg.MODE}

    # DB
    try:
        con.execute("SELECT 1;").fetchone()
        components["db"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["db"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    # Broker (fetch_ticker c коротким таймаутом — у нас таймауты уже внутри адаптера)
    try:
        # используем символ из конфигов, но ошибки не фатальны
        broker.fetch_ticker(cfg.SYMBOL)
        components["broker"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    # Time drift (если модуль есть)
    try:
        drift_ms = measure_time_drift(cfg.TIME_DRIFT_URLS or None, timeout=cfg.BROKER_TIMEOUT_SEC)
        components["time"] = {
            "status": "ok" if abs(drift_ms) <= cfg.TIME_DRIFT_LIMIT_MS else "drift",
            "drift_ms": drift_ms,
            "limit_ms": cfg.TIME_DRIFT_LIMIT_MS,
        }
    except Exception as e:
        components["time"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    # миграции
    if getattr(app.state, "migration_error", None):
        components["migrations"] = {"status": "error", "detail": app.state.migration_error}
    else:
        components["migrations"] = {"status": "ok"}

    # сводный статус
    statuses = [v["status"] for k, v in components.items() if isinstance(v, dict)]
    if any(s.startswith("error") for s in statuses) or any(s == "drift" for s in statuses):
        status = "degraded"
        lvl = "major" if any(s.startswith("error") for s in statuses) else "minor"
    else:
        status = "healthy"
        lvl = "none"

    return {"status": status, "degradation_level": lvl, "components": components}


@app.get("/metrics", response_class=None)
def metrics() -> Any:
    return metrics_export()


@app.post("/tick")
def tick(body: TickIn) -> dict:
    cfg: Settings = app.state.cfg
    broker = app.state.broker
    repos: Repos = app.state.repos

    symbol = body.symbol or cfg.SYMBOL
    timeframe = body.timeframe or cfg.TIMEFRAME
    limit = body.limit or cfg.LIMIT

    try:
        res = uc_eval_and_execute(
            cfg,
            broker,
            repos,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
        return res
    except Exception as e:
        # ошибки не пробрасываем наружу, чтобы не падал оркестратор
        return {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}


@app.get("/why_last")
def why_last(symbol: Optional[str] = None, timeframe: Optional[str] = None) -> dict:
    """
    Возвращает последнее Decision для пары symbol/timeframe (с explain),
    которое было сохранено в таблицу `decisions` (Шаг 79).
    """
    cfg: Settings = app.state.cfg
    repos: Repos = app.state.repos

    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME

    if not getattr(repos, "decisions", None):
        raise HTTPException(status_code=501, detail="Decisions repo not configured")

    row = repos.decisions.get_last(symbol=sym, timeframe=tf)
    if not row:
        raise HTTPException(status_code=404, detail="No decisions found")

    return {"status": "ok", "symbol": sym, "timeframe": tf, "decision": row}
