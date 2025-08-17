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
    from crypto_ai_bot.core.storage.migrations.runner import apply_all as apply_migrations
except Exception:  # pragma: no cover
    apply_migrations = None  # мягкая деградация

from crypto_ai_bot.core.storage.repositories import (
    SqliteTradeRepository,
    SqlitePositionRepository,
    SqliteSnapshotRepository,
    SqliteAuditRepository,
    SqliteIdempotencyRepository,
    SqliteDecisionsRepository,  # decisions repo
)

# --- broker factory ---
from crypto_ai_bot.core.brokers.base import create_broker

# --- use-cases ---
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute

# --- metrics / time sync / http ---
from crypto_ai_bot.utils.metrics import inc, observe, export as metrics_export
from crypto_ai_bot.utils.http_client import get_http_client
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift  # если внедрён ранее
except Exception:  # pragma: no cover
    def measure_time_drift(urls: Optional[list[str]] = None, timeout: float = 1.0) -> int:
        return 0

# --- telegram adapter ---
from crypto_ai_bot.app.adapters.telegram import handle_update as tg_handle, TgDeps


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
    uow: Optional[Any] = None

def _build_repos(con: sqlite3.Connection) -> Repos:
    return Repos(
        trades=SqliteTradeRepository(con),
        positions=SqlitePositionRepository(con),
        snapshots=SqliteSnapshotRepository(con),
        audit=SqliteAuditRepository(con),
        idempotency=SqliteIdempotencyRepository(con),
        decisions=SqliteDecisionsRepository(con),
        uow=None,
    )


# =========================
#        FASTAPI
# =========================
app = FastAPI(title="crypto-ai-bot")

@app.on_event("startup")
def on_startup() -> None:
    cfg = Settings.build()
    app.state.cfg = cfg

    con = connect(cfg.DB_PATH)
    app.state.con = con

    if apply_migrations is not None:
        try:
            apply_migrations(con)
        except Exception as e:  # pragma: no cover
            app.state.migration_error = str(e)

    app.state.repos = _build_repos(con)
    app.state.broker = create_broker(mode=cfg.MODE, settings=cfg, http_client=None)

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

    # Broker
    try:
        broker.fetch_ticker(cfg.SYMBOL)
        components["broker"] = {"status": "ok", "latency_ms": 0}
    except Exception as e:
        components["broker"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    # Time drift
    try:
        drift_ms = measure_time_drift(cfg.TIME_DRIFT_URLS or None, timeout=cfg.BROKER_TIMEOUT_SEC)
        components["time"] = {
            "status": "ok" if abs(drift_ms) <= cfg.TIME_DRIFT_LIMIT_MS else "drift",
            "drift_ms": drift_ms,
            "limit_ms": cfg.TIME_DRIFT_LIMIT_MS,
        }
    except Exception as e:
        components["time"] = {"status": f"error:{type(e).__name__}", "detail": str(e)}

    # migrations
    if getattr(app.state, "migration_error", None):
        components["migrations"] = {"status": "error", "detail": app.state.migration_error}
    else:
        components["migrations"] = {"status": "ok"}

    statuses = [v["status"] for v in components.values() if isinstance(v, dict)]
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
        return {"status": "error", "error": f"tick_failed: {type(e).__name__}: {e}"}


@app.get("/why_last")
def why_last(symbol: Optional[str] = None, timeframe: Optional[str] = None) -> dict:
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


# ============ Telegram webhook ============
@app.post("/telegram")
async def telegram_webhook(req: Request) -> dict:
    cfg: Settings = app.state.cfg

    # Защита: секретный токен в заголовке (если настроен)
    secret = (req.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
    if getattr(cfg, "TELEGRAM_SECRET_TOKEN", None):
        if secret != cfg.TELEGRAM_SECRET_TOKEN:
            raise HTTPException(status_code=403, detail="invalid telegram secret")

    update = await req.json()

    # Инжектируем коллбеки для адаптера:
    def _tick_call(symbol: str, timeframe: str, limit: int) -> dict:
        return tick(TickIn(symbol=symbol, timeframe=timeframe, limit=limit))  # reuse our endpoint logic

    def _why_last_call(symbol: str, timeframe: str) -> Optional[dict]:
        repos: Repos = app.state.repos
        if not getattr(repos, "decisions", None):
            return None
        return repos.decisions.get_last(symbol=symbol, timeframe=timeframe)

    deps = TgDeps(
        tick_call=_tick_call,
        why_last_call=_why_last_call,
        default_symbol=cfg.SYMBOL,
        default_timeframe=cfg.TIMEFRAME,
        default_limit=cfg.LIMIT,
    )

    reply = tg_handle(update, deps)

    # Отправляем сообщение через Telegram API, если есть токен
    msg = {
        "chat_id": reply.get("chat_id"),
        "text": reply.get("text", ""),
        "parse_mode": reply.get("parse_mode") or "Markdown",
        "disable_web_page_preview": True,
    }

    if getattr(cfg, "TELEGRAM_BOT_TOKEN", None):
        http = get_http_client()
        try:
            http.post_json(
                f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage",
                json=msg,
                timeout=cfg.BROKER_TIMEOUT_SEC,
            )
            inc("telegram_send_total", {"status": "ok"})
        except Exception as e:
            inc("telegram_send_total", {"status": "error"})
            # Возвращаем текст, чтобы можно было увидеть его в логах даже при ошибке отправки
            return {"status": "send_error", "detail": str(e), "echo": msg}

    return {"status": "ok", "echo": msg}
