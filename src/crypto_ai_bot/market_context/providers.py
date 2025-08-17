# src/crypto_ai_bot/market_context/providers.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import json

from crypto_ai_bot.utils.cache import TTLCache
from crypto_ai_bot.utils import metrics

# Локальный кэш для всех провайдеров (сконфигурируем TTL снаружи)
_CACHE: TTLCache = TTLCache(ttl_sec=300, maxsize=128)

def _cache_ttl_reset(ttl_sec: int) -> None:
    # Пересоздаём кэш, если TTL поменяли в конфиге
    global _CACHE
    if _CACHE.ttl != int(ttl_sec):
        _CACHE = TTLCache(ttl_sec=int(ttl_sec), maxsize=128)

def _fetch_json(http, url: str, *, timeout: float) -> Optional[Dict[str, Any]]:
    r = http.get(url, timeout=timeout)
    if getattr(r, "status_code", 500) >= 400:
        raise RuntimeError(f"http_{r.status_code}")
    try:
        return r.json()
    except Exception:
        # fallback: вдруг сервер прислал текст/JS
        return json.loads(r.text)

def btc_dominance(cfg, http, breaker) -> Optional[float]:
    """
    Источник по умолчанию: Coingecko global.
    Возвращает процент доминации BTC (float), либо None.
    """
    url = getattr(cfg, "CONTEXT_BTC_DOMINANCE_URL", "https://api.coingecko.com/api/v3/global")
    if not url:
        return None

    _cache_ttl_reset(int(getattr(cfg, "CONTEXT_CACHE_TTL_SEC", 300)))
    key = f"ctx:btc_dominance:{url}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    try:
        def _call():
            return _fetch_json(http, url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)))
        obj = breaker.call(_call, key="ctx.btc_dominance", timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)) + 0.2)
        val = None
        try:
            # coingecko: {"data":{"market_cap_percentage":{"btc": 52.1, ...}}}
            val = float(obj["data"]["market_cap_percentage"]["btc"])
        except Exception:
            val = None
        status = "ok" if val is not None else "parse_error"
        metrics.inc("context_fetch_total", {"source": "btc_dominance", "status": status})
        if val is not None:
            metrics.set("context_value", val, {"metric": "btc_dominance_percent"})
            _CACHE.set(key, val)
        return val
    except Exception as e:
        metrics.inc("context_fetch_total", {"source": "btc_dominance", "status": "error"})
        return None

def fear_greed(cfg, http, breaker) -> Tuple[Optional[float], Optional[str]]:
    """
    Источник по умолчанию: alternative.me FNG API.
    Возвращает (value [0..100], classification), или (None, None).
    """
    url = getattr(cfg, "CONTEXT_FEAR_GREED_URL", "https://api.alternative.me/fng/?limit=1")
    if not url:
        return (None, None)

    _cache_ttl_reset(int(getattr(cfg, "CONTEXT_CACHE_TTL_SEC", 300)))
    key = f"ctx:fng:{url}"
    cached = _CACHE.get(key)
    if cached is not None:
        v, cls = cached
        return (v, cls)

    try:
        def _call():
            return _fetch_json(http, url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)))
        obj = breaker.call(_call, key="ctx.fear_greed", timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0)) + 0.2)
        val = None
        cls = None
        try:
            # alternative.me: {"data":[{"value":"72","value_classification":"Greed",...}]}
            rec = (obj.get("data") or [{}])[0]
            val = float(rec.get("value")) if rec.get("value") is not None else None
            cls = str(rec.get("value_classification")) if rec.get("value_classification") is not None else None
        except Exception:
            val = None
            cls = None
        status = "ok" if val is not None else "parse_error"
        metrics.inc("context_fetch_total", {"source": "fear_greed", "status": status})
        if val is not None:
            metrics.set("context_value", val, {"metric": "fear_greed_index"})
        _CACHE.set(key, (val, cls))
        return (val, cls)
    except Exception:
        metrics.inc("context_fetch_total", {"source": "fear_greed", "status": "error"})
        return (None, None)

def dxy_index(cfg, http, breaker) -> Optional[float]:
    """
    DXY: по умолчанию выключен (требуются ключи/платные API).
    Можно указать произвольный JSON-эндпоинт через CONTEXT_DXY_URL,
    который возвращает {"value": <число>}.
    """
    url = getattr(cfg, "CONTEXT_DXY_URL", "")
    if not url:
        return None

    _cache_ttl_reset(int(getattr(cfg, "CONTEXT_CACHE_TTL_SEC", 300)))
    key = f"ctx:dxy:{url}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    try:
        def _call():
            return _fetch_json(http, url, timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.5)))
        obj = breaker.call(_call, key="ctx.dxy", timeout=float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.5)) + 0.2)
        val = None
        try:
            # ожидаем простой формат: {"value": 102.31}
            val = float(obj.get("value"))
        except Exception:
            val = None
        status = "ok" if val is not None else "parse_error"
        metrics.inc("context_fetch_total", {"source": "dxy", "status": status})
        if val is not None:
            metrics.set("context_value", val, {"metric": "dxy_index"})
            _CACHE.set(key, val)
        return val
    except Exception:
        metrics.inc("context_fetch_total", {"source": "dxy", "status": "error"})
        return None
