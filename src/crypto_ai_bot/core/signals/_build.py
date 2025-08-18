# внутри build(...), где формируете context:
from crypto_ai_bot.utils import metrics
try:
    # если есть утилита синхронизации времени — используем
    from crypto_ai_bot.utils.time_sync import measure_time_drift_ms
except Exception:
    measure_time_drift_ms = None

# ...
context: dict = {
    # ... ваши уже существующие поля, например:
    # "positions_open": n_open,
    # "positions_notional": notional,
}

# добавим drift, но без жёсткой зависимости:
drift_val = None
if measure_time_drift_ms:
    try:
        drift_val = float(measure_time_drift_ms(timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0))))
    except Exception:
        metrics.inc("context_time_drift_errors_total")
        drift_val = None
context["time_drift_ms"] = drift_val

return {"features": features, "context": context}
