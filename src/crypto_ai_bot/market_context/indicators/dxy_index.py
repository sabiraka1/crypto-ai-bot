# src/crypto_ai_bot/market_context/indicators/dxy_index.py
from __future__ import annotations
from typing import Any, Optional


def fetch_dxy(http: Any, breaker: Any, url: str, *, timeout: float = 2.0) -> Optional[float]:
    """
    Источник для DXY задаётся вручную (Settings.CONTEXT_DXY_URL).
    Ожидается JSON со значением индекса в поле "value" или верхнего уровня, либо {"dxy": 104.2}.
    Возвращаем нормализованное значение ~ (100..110) → в 0..1 через простую линейную нормализацию:
       score = clamp((value - 90) / 30, 0..1)
    """
    if not url:
        return None
    try:
        def _call():
            return http.get_json(url, timeout=timeout)
        data = breaker.call(_call, key="ctx.dxy", timeout=timeout + 0.5)
    except Exception:
        return None

    val = None
    try:
        if isinstance(data, dict):
            if "value" in data:
                val = float(data["value"])
            elif "dxy" in data:
                val = float(data["dxy"])
            else:
                # попробуем первый числовой
                for v in data.values():
                    try:
                        val = float(v)
                        break
                    except Exception:
                        continue
    except Exception:
        val = None

    if val is None:
        return None

    # нормализация (грубая, но стабильная)
    score = (val - 90.0) / 30.0
    return max(0.0, min(1.0, float(score)))
