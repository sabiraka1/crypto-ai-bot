# -*- coding: utf-8 -*-
"""
Risk checks and validation pipeline for opening/closing orders.
Lightweight, no heavy deps. Works with a ccxt-like exchange.
Path: src/crypto_ai_bot/trading/risk.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def _get_ticker(exchange: Any, symbol: str) -> Dict[str, Any]:
    try:
        if hasattr(exchange, "fetch_ticker"):
            t = exchange.fetch_ticker(symbol) or {}
            # normalize a few numeric fields
            for k in ("bid", "ask", "last", "close", "baseVolume", "quoteVolume"):
                if k in t and t[k] is not None:
                    try:
                        t[k] = float(t[k])
                    except Exception:
                        pass
            return t
    except Exception:
        return {}
    return {}


def _spread_bps(t: Dict[str, Any]) -> Optional[float]:
    bid = float(t.get("bid") or 0.0)
    ask = float(t.get("ask") or 0.0)
    if bid > 0 and ask > 0 and ask >= bid:
        mid = (ask + bid) / 2.0
        if mid > 0:
            return (ask - bid) / mid * 10_000.0
    return None


def _quote_volume_usd(t: Dict[str, Any]) -> Optional[float]:
    last = float(t.get("last") or t.get("close") or 0.0)
    # common fields
    for key in ("quoteVolume", "quoteVolume24h"):
        v = t.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    info = t.get("info") or {}
    for key in ("quote_volume", "turnover", "turnover_24h", "quoteTurnover", "volumeQuote"):
        if key in info and info[key] is not None:
            try:
                return float(info[key])
            except Exception:
                pass
    # fallback: baseVolume * last
    base_v = t.get("baseVolume")
    if base_v is None and isinstance(info, dict):
        for key in ("base_volume", "volume", "volume_24h"):
            if key in info:
                base_v = info.get(key)
                break
    try:
        base_v = float(base_v) if base_v is not None else None
    except Exception:
        base_v = None
    if base_v is not None and last > 0:
        return base_v * last
    return None


def check_trading_hours(cfg) -> Tuple[bool, Optional[str]]:
    start_h = int(getattr(cfg, "TRADING_HOUR_START", 0))
    end_h = int(getattr(cfg, "TRADING_HOUR_END", 24))
    hour = datetime.now(timezone.utc).hour
    if start_h <= hour < end_h:
        return True, None
    return False, f"outside trading hours UTC {start_h}-{end_h}"


def check_spread(cfg, exchange: Any, symbol: str) -> Tuple[bool, Optional[str]]:
    limit_bps = float(getattr(cfg, "MAX_SPREAD_BPS", 0) or 0)
    if limit_bps <= 0:
        return True, None  # disabled
    t = _get_ticker(exchange, symbol)
    bps = _spread_bps(t)
    if bps is None:
        return True, None  # can't compute в†’ don't block
    if bps > limit_bps:
        return False, f"spread {bps:.1f}bps > limit {limit_bps:.1f}bps"
    return True, None


def check_volume_24h(cfg, exchange: Any, symbol: str) -> Tuple[bool, Optional[str]]:
    min_usd = float(getattr(cfg, "MIN_24H_VOLUME_USD", 0) or 0)
    if min_usd <= 0:
        return True, None  # disabled
    t = _get_ticker(exchange, symbol)
    qv = _quote_volume_usd(t)
    if qv is None:
        return True, None  # can't compute в†’ don't block
    if qv < min_usd:
        return False, f"24h quote volume {qv:.0f} < min {min_usd:.0f}"
    return True, None


def validate_open(cfg, exchange: Any, symbol: str, indicators: Optional[Dict[str, float]] = None) -> Tuple[bool, Optional[str]]:
    """
    High-level gate before opening a position.
    Order: hours в†’ spread в†’ liquidity (stop on first failure).
    """
    ok, reason = check_trading_hours(cfg)
    if not ok:
        return False, reason

    ok, reason = check_spread(cfg, exchange, symbol)
    if not ok:
        return False, reason

    ok, reason = check_volume_24h(cfg, exchange, symbol)
    if not ok:
        return False, reason

    # placeholders for future checks: ATR gates, context penalties, drawdown caps, etc.
    return True, None

