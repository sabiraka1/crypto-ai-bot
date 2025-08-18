# src/crypto_ai_bot/core/validators/config.py
from __future__ import annotations

from typing import Any, Dict, List

def _ok(code: str, **details: Any) -> Dict[str, Any]:
    return {"status": "ok", "code": code, **details}

def _warn(code: str, **details: Any) -> Dict[str, Any]:
    return {"status": "warn", "code": code, **details}

def _err(code: str, **details: Any) -> Dict[str, Any]:
    return {"status": "error", "code": code, **details}

def validate_config(
    cfg: Any,
    *,
    http: Any = None,
    conn: Any = None,
    bus: Any = None,
    breaker: Any = None,
) -> Dict[str, Any]:
    """
    Возвращает агрегат по проверкам:
    { "ok": bool, "errors": [...], "warnings": [...], "checks": {name: {...}} }
    """
    checks: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    warnings: List[str] = []

    # MODE
    mode = str(getattr(cfg, "MODE", "paper")).lower()
    if mode not in {"paper", "backtest", "live"}:
        checks["mode"] = _err("invalid_mode", mode=mode, allowed=["paper", "backtest", "live"])
        errors.append("invalid_mode")
    else:
        checks["mode"] = _ok("mode_ok", mode=mode)

    # Broker creds
    if mode == "live":
        api_key = getattr(cfg, "API_KEY", None)
        api_secret = getattr(cfg, "API_SECRET", None)
        if not api_key or not api_secret:
            checks["broker_creds"] = _err("missing_api_credentials_live")
            errors.append("missing_api_credentials_live")
        else:
            checks["broker_creds"] = _ok("broker_creds_ok")
    else:
        if getattr(cfg, "API_KEY", None) or getattr(cfg, "API_SECRET", None):
            checks["broker_creds"] = _warn("api_credentials_present_nonlive")
            warnings.append("api_credentials_present_nonlive")
        else:
            checks["broker_creds"] = _ok("broker_creds_not_required")

    # Rate limits
    rl_eval = int(getattr(cfg, "RL_EVALUATE_PER_MIN", 60) or 0)
    rl_ord  = int(getattr(cfg, "RL_ORDERS_PER_MIN", 10) or 0)
    if rl_eval > 0 and rl_ord > 0:
        checks["rate_limits"] = _ok("rate_limits_ok", evaluate=rl_eval, orders=rl_ord)
    else:
        checks["rate_limits"] = _err("rate_limits_non_positive", evaluate=rl_eval, orders=rl_ord)
        errors.append("rate_limits_non_positive")

    # Budgets
    b_dec = int(getattr(cfg, "PERF_BUDGET_DECISION_P99_MS", 0) or 0)
    b_ord = int(getattr(cfg, "PERF_BUDGET_ORDER_P99_MS", 0) or 0)
    b_flow= int(getattr(cfg, "PERF_BUDGET_FLOW_P99_MS", 0) or 0)
    if min(b_dec, b_ord, b_flow) < 0:
        checks["budgets"] = _err("budget_negative", decision=b_dec, order=b_ord, flow=b_flow)
        errors.append("budget_negative")
    else:
        checks["budgets"] = _ok("budgets_ok", decision=b_dec, order=b_ord, flow=b_flow)

    # Context preset vs manual
    preset = str(getattr(cfg, "CONTEXT_PRESET", "off") or "off").lower()
    alpha  = float(getattr(cfg, "CONTEXT_DECISION_WEIGHT", 0) or 0.0)
    w_dom  = float(getattr(cfg, "CTX_BTC_DOM_WEIGHT", 0) or 0.0)
    w_fng  = float(getattr(cfg, "CTX_FNG_WEIGHT", 0) or 0.0)
    w_dxy  = float(getattr(cfg, "CTX_DXY_WEIGHT", 0) or 0.0)
    manual_nonzero = (alpha + w_dom + w_fng + w_dxy) > 0.0
    if preset != "off" and manual_nonzero:
        checks["context_weights"] = _warn("preset_ignored_due_manual_weights",
                                          preset=preset, alpha=alpha, w_dom=w_dom, w_fng=w_fng, w_dxy=w_dxy)
        warnings.append("preset_ignored_due_manual_weights")
    else:
        checks["context_weights"] = _ok("context_weights_ok",
                                        preset=preset, alpha=alpha, w_dom=w_dom, w_fng=w_fng, w_dxy=w_dxy)

    # Alerts
    if getattr(cfg, "ALERT_ON_DLQ", True) or getattr(cfg, "ALERT_ON_LATENCY", False):
        token  = getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
        chatid = getattr(cfg, "ALERT_TELEGRAM_CHAT_ID", None)
        if not token or not chatid:
            checks["alerts"] = _warn("alerts_enabled_but_no_telegram",
                                     on_dlq=bool(getattr(cfg, "ALERT_ON_DLQ", True)),
                                     on_latency=bool(getattr(cfg, "ALERT_ON_LATENCY", False)))
            warnings.append("alerts_enabled_but_no_telegram")
        else:
            checks["alerts"] = _ok("alerts_ok")
    else:
        checks["alerts"] = _ok("alerts_disabled")

    # DB connectivity
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            checks["database"] = _ok("db_ok")
        except Exception as e:
            checks["database"] = _err("db_error", error=f"{type(e).__name__}: {e}")
            errors.append("db_error")
    else:
        checks["database"] = _warn("db_conn_not_provided")
        warnings.append("db_conn_not_provided")

    # Bus / DLQ
    if bus is not None and hasattr(bus, "health"):
        try:
            h = bus.health()
            dlq = int(h.get("dlq_size") or h.get("dlq_len") or h.get("dlq", 0) or 0)
            if dlq > 100:
                checks["bus"] = _warn("dlq_not_empty", dlq=dlq)
                warnings.append("dlq_not_empty")
            else:
                checks["bus"] = _ok("bus_ok", dlq=dlq)
        except Exception as e:
            checks["bus"] = _warn("bus_health_error", error=f"{type(e).__name__}: {e}")
            warnings.append("bus_health_error")
    else:
        checks["bus"] = _warn("bus_not_provided")
        warnings.append("bus_not_provided")

    # Breaker
    if breaker is not None and hasattr(breaker, "get_stats"):
        try:
            stats = breaker.get_stats()
            critical = {"fetch_ticker", "fetch_order_book", "fetch_ohlcv", "create_order"}
            opened = [k for k, v in stats.items()
                      if v.get("state") == "open" and (k in critical or any(c in k for c in critical))]
            if opened:
                checks["breaker"] = _warn("breaker_open_critical", keys=opened)
                warnings.append("breaker_open_critical")
            else:
                checks["breaker"] = _ok("breaker_ok")
        except Exception as e:
            checks["breaker"] = _warn("breaker_stats_error", error=f"{type(e).__name__}: {e}")
            warnings.append("breaker_stats_error")
    else:
        checks["breaker"] = _warn("breaker_not_provided")
        warnings.append("breaker_not_provided")

    # Time sync
    if http is not None:
        try:
            from crypto_ai_bot.utils.time_sync import check_time_sync_status
            urls = getattr(cfg, "TIME_DRIFT_URLS", None) or []
            limit = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000) or 1000)
            ok, drift_ms, details = check_time_sync_status(cfg, http, urls=urls, timeout=1.5, limit_ms=limit)
            if drift_ms is None:
                checks["time_sync"] = _warn("time_sync_unknown", **details)
                warnings.append("time_sync_unknown")
            elif ok:
                checks["time_sync"] = _ok("time_sync_ok", drift_ms=int(drift_ms), limit_ms=limit, used=details.get("used"))
            else:
                checks["time_sync"] = _err("time_sync_drift_exceeded", drift_ms=int(drift_ms),
                                           limit_ms=limit, used=details.get("used"))
                errors.append("time_sync_drift_exceeded")
        except Exception as e:
            checks["time_sync"] = _warn("time_sync_check_failed", error=f"{type(e).__name__}: {e}")
            warnings.append("time_sync_check_failed")
    else:
        checks["time_sync"] = _warn("http_not_provided")
        warnings.append("http_not_provided")

    ok_all = len(errors) == 0
    return {"ok": ok_all, "errors": errors, "warnings": warnings, "checks": checks}
