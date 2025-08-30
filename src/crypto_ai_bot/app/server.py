@app.on_event("startup")
async def _startup() -> None:
    global _container
    _container = build_container()

    # Жёсткое требование токена для API в live-режиме, если включён флаг
    try:
        require_token = bool(int(getattr(_container.settings, "REQUIRE_API_TOKEN_IN_LIVE", 0)))
    except Exception:
        require_token = False
    if (_container.settings.MODE or "").lower() == "live" and require_token:
        if not (_container.settings.API_TOKEN or "").strip():
            _container = None
            raise RuntimeError("API token is required in LIVE mode (set REQUIRE_API_TOKEN_IN_LIVE=1)")

    # --- Стартовый reconcile-барьер ---
    try:
        from crypto_ai_bot.utils.decimal import dec
        from crypto_ai_bot.utils.time import now_ms
        
        tol = dec(str(getattr(_container.settings, "RECONCILE_READY_TOLERANCE_BASE", "0.00000010")))
        pos = _container.storage.positions.get_position(_container.settings.SYMBOL)
        bal = await _container.broker.fetch_balance(_container.settings.SYMBOL)
        diff = (bal.free_base or dec("0")) - (pos.base_qty or dec("0"))
        
        if abs(diff) > tol:
            if bool(getattr(_container.settings, "RECONCILE_AUTOFIX", 0)):
                # Автоматическое выравнивание позиции
                add_rec = getattr(_container.storage.trades, "add_reconciliation_trade", None)
                if callable(add_rec):
                    add_rec({
                        "symbol": _container.settings.SYMBOL,
                        "side": ("buy" if diff > 0 else "sell"),
                        "amount": str(abs(diff)),
                        "status": "reconciliation",
                        "ts_ms": now_ms(),
                        "client_order_id": f"reconcile-start-{_container.settings.SYMBOL}-{now_ms()}",
                    })
                _container.storage.positions.set_base_qty(_container.settings.SYMBOL, bal.free_base or dec("0"))
                _log.info("startup_reconcile_autofix_applied", extra={
                    "symbol": _container.settings.SYMBOL,
                    "diff": str(diff),
                    "local_before": str(pos.base_qty),
                    "exchange": str(bal.free_base)
                })
            else:
                # Блокировка запуска при расхождении
                _log.error("startup_reconcile_blocked", extra={
                    "symbol": _container.settings.SYMBOL,
                    "expected": str(bal.free_base), 
                    "local": str(pos.base_qty),
                    "diff": str(diff)
                })
                raise RuntimeError(
                    f"Position mismatch at startup: exchange={bal.free_base} local={pos.base_qty}. "
                    f"Enable RECONCILE_AUTOFIX=1 or fix manually."
                )
        else:
            _log.info("startup_reconcile_ok", extra={
                "symbol": _container.settings.SYMBOL,
                "position": str(pos.base_qty),
                "diff": str(diff)
            })
    except RuntimeError:
        # Пробрасываем RuntimeError для остановки
        raise
    except Exception as exc:
        _log.error("startup_reconcile_failed", extra={"error": str(exc)})
        # Не стартуем торговлю и даём 503 на /ready
        return

    # Автостарт оркестратора
    autostart = bool(_container.settings.TRADER_AUTOSTART) or _container.settings.MODE == "live"
    if autostart:
        loop = asyncio.get_running_loop()
        loop.call_soon(_container.orchestrator.start)
        _log.info("orchestrator_autostart_enabled", extra={"mode": _container.settings.MODE})