# src/crypto_ai_bot/core/validators/__init__.py
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, List


def _ok(code: str, **kw) -> Dict[str, Any]:
    return {"status": "ok", "code": code, **kw}


def _err(code: str, **kw) -> Dict[str, Any]:
    return {"status": "error", "code": code, **kw}


def _warn(code: str, **kw) -> Dict[str, Any]:
    return {"status": "warn", "code": code, **kw}


def _check_db(conn: Any, path_hint: Optional[str]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        conn.execute("SELECT 1")
        lat_ms = int((time.perf_counter() - t0) * 1000)
        # если путь задан и не :memory: — проверим директорию на запись
        if path_hint and not str(path_hint).startswith(":"):
            try:
                d = os.path.dirname(os.path.abspath(path_hint)) or "."
                test_path = os.path.join(d, ".write_test.tmp")
                with open(test_path, "wb") as f:
                    f.write(b"x")
                os.remove(test_path)
            except Exception as e:
                return _warn("db_dir_not_writable", path=path_hint, error=f"{type(e).__name__}: {e}", latency_ms=lat_ms)
        return _ok("db_ok", latency_ms=lat_ms, path=path_hint)
    except Exception as e:
        return _err("db_failed", error=f"{type(e).__name__}: {e}")


def _check_broker(cfg: Any, broker: Any) -> Dict[str, Any]:
    sym = getattr(cfg, "SYMBOL", "BTC/USDT")
    t0 = time.perf_counter()
    try:
        _ = broker.fetch_ticker(sym)
        lat_ms = int((time.perf_counter() - t0) * 1000)
        return _ok("broker_ok", latency_ms=lat_ms, symbol=sym)
    except Exception as e:
        return _err("broker_failed", error=f"{type(e).__name__}: {e}", symbol=sym)


def _check_bus(bus: Any) -> Dict[str, Any]:
    try:
        rep = bus.health()
        if isinstance(rep, dict):
            return _ok("bus_ok", **rep)
        return _warn("bus_unknown", detail=repr(rep))
    except Exception as e:
        return _err("bus_failed", error=f"{type(e).__name__}: {e}")


def _check_time_sync(cfg: Any, http: Any) -> Dict[str, Any]:
    try:
        from crypto_ai_bot.core.risk.rules import check_time_sync
    except Exception:
        return _warn("time_sync_unavailable")
    return check_time_sync(cfg, http)


def _check_settings(cfg: Any) -> Dict[str, Any]:
    problems: List[str] = []

    # Базовые поля
    if not getattr(cfg, "SYMBOL", None):
        problems.append("SYMBOL missing")
    if not getattr(cfg, "TIMEFRAME", None):
        problems.append("TIMEFRAME missing")
    if getattr(cfg, "MODE", "").lower() not in {"paper", "live", "backtest"}:
        problems.append("MODE should be paper|live|backtest")

    # Бюджеты p99 — не обязательно, но хорошо иметь >0
    for k in ("PERF_BUDGET_DECISION_P99_MS", "PERF_BUDGET_ORDER_P99_MS", "PERF_BUDGET_FLOW_P99_MS"):
        v = int(getattr(cfg, k, 0) or 0)
        if v <= 0:
            problems.append(f"{k} is 0 (set sensible default)")

    if problems:
        return _warn("settings_warnings", problems=problems)
    return _ok("settings_ok")


def validate_config(cfg: Any, *, http: Any, conn: Any, bus: Any, breaker: Any) -> Dict[str, Any]:
    """
    Комплексная проверка, отдаёт JSON, пригодный для /config/validate.
    """
    checks = {
        "settings": _check_settings(cfg),
        "db": _check_db(conn, getattr(cfg, "DB_PATH", None)),
        "broker": _check_broker(cfg, getattr(cfg, "BROKER", None) or breaker or object()),
        "bus": _check_bus(bus),
        "time_sync": _check_time_sync(cfg, http),
    }

    blocked = [k for k, v in checks.items() if v.get("status") == "error"]
    ok = len(blocked) == 0
    return {"ok": ok, "blocked": blocked, "checks": checks}
