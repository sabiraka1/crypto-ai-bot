# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional


def risk_concurrent_positions_blocked(
    *,
    positions_repo: Any,
    symbol: str,
    max_open_positions: int = 1,
) -> Dict[str, Any]:
    """
    Блокируем открытие новой позиции, если уже есть открытая,
    либо если общее число открытых позиций превысит лимит.
    """
    try:
        rows = positions_repo.get_open()
    except Exception:
        rows = []
    already_long = any(str(r.get("symbol")) == symbol and float(r.get("qty", 0)) > 0 for r in rows)
    if already_long:
        return {"blocked": True, "reason": "already_long"}
    if len(rows) >= int(max_open_positions):
        return {"blocked": True, "reason": "too_many_open_positions"}
    return {"blocked": False}


def realized_pnl_since_ms(
    *,
    trades_repo: Any,
    since_ms: int,
    symbol: Optional[str] = None,
) -> float:
    """
    Простейший расчёт реализованного PnL с момента since_ms (long-only).
    """
    try:
        rows = trades_repo.list_since_ms(since_ms, symbol=symbol)
    except Exception:
        rows = []

    cash = 0.0
    pos = 0.0
    pnl = 0.0
    for t in rows:
        side = str(t.get("side", "")).lower()
        px = float(t.get("price") or 0.0)
        qty = float(t.get("qty") or t.get("amount") or 0.0)
        if px <= 0 or qty <= 0:
            continue
        if side == "buy":
            cash -= px * qty
            pos += qty
        elif side == "sell":
            if pos <= 0:
                continue
            q = min(pos, qty)
            pnl += q * px + cash * (q / max(pos, 1e-9))
            pos -= q
            if pos > 0:
                cash *= pos / max(pos + q, 1e-9)
            else:
                cash = 0.0
    return float(pnl)


def risk_daily_loss_blocked(
    *,
    trades_repo: Any,
    daily_loss_limit_pct: float,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Блокируем торговлю при превышении дневного лимита потерь в %.
    """
    # начало суток (UTC) — можно заменить на локаль по требованию
    now = int(time.time() * 1000)
    start_of_day_ms = now - (now % (24 * 60 * 60 * 1000))

    realized = realized_pnl_since_ms(trades_repo=trades_repo, since_ms=start_of_day_ms, symbol=symbol)
    # чтобы посчитать % к депозиту — нужен базовый капитал; в простом варианте считаем по POSITION_SIZE_USD
    # если нужно — подмешай cfg.BASE_CAPITAL_USD
    base = 0.0
    try:
        base = float(getattr(trades_repo, "base_capital_usd", 0.0))  # опционально
    except Exception:
        base = 0.0

    # если базовый капитал неизвестен — сравним с позиционным лимитом
    if base <= 0.0:
        limit_hit = daily_loss_limit_pct <= 0.0 and realized < 0.0
    else:
        pct = (realized / base) * 100.0
        limit_hit = pct <= -abs(float(daily_loss_limit_pct))

    if limit_hit:
        return {"blocked": True, "reason": "daily_loss_limit_exceeded", "realized_pnl": realized}
    return {"blocked": False, "realized_pnl": realized}
