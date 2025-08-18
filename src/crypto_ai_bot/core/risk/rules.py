# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

import time
import logging
from typing import Any, Dict, Optional, Iterable

logger = logging.getLogger("risk.rules")


def _iter_trades_since(trades_repo: Any, since_ms: int, symbol: Optional[str]) -> Iterable[Dict[str, Any]]:
    # Обёртка для единообразной обработки ошибок и логов
    try:
        if hasattr(trades_repo, "list_since_ms"):
            return trades_repo.list_since_ms(since_ms, symbol=symbol)
        # fallback — если такой функции нет
        rows = trades_repo.list_by_symbol(symbol, limit=10000) if symbol else trades_repo.list_all(limit=10000)
        return [t for t in rows if int(t.get("ts_ms", 0)) >= since_ms]
    except Exception:
        logger.exception("trades_repo iteration failed (since_ms=%s, symbol=%s)", since_ms, symbol)
        return []


def risk_concurrent_positions_blocked(
    *,
    positions_repo: Any,
    symbol: str,
    max_open_positions: int = 1,
) -> Dict[str, Any]:
    """
    Блокируем открытие новой позиции, если уже открыта по символу,
    либо если общее число открытых позиций >= max_open_positions.
    Любая ошибка репозитория — лог и мягкий отказ (blocked=True с reason).
    """
    try:
        rows = positions_repo.get_open()
        already_long = any(str(r.get("symbol")) == symbol and float(r.get("qty", 0)) > 0 for r in rows)
        if already_long:
            return {"blocked": True, "reason": "already_long"}

        if len(rows) >= int(max_open_positions):
            return {"blocked": True, "reason": "too_many_open_positions"}

        return {"blocked": False, "reason": None}

    except Exception:
        logger.exception("risk_concurrent_positions_blocked failed (symbol=%s)", symbol)
        # мягкий отказ — лучше перестраховаться, чем открыть лишнюю позицию
        return {"blocked": True, "reason": "risk_internal_error"}


def realized_pnl_since_ms(
    *,
    trades_repo: Any,
    since_ms: int,
    symbol: Optional[str] = None,
) -> float:
    """
    Простейший расчёт реализованного PnL с момента since_ms (long-only FIFO).
    Любая ошибка — лог и возврат 0.0 (консервативно).
    """
    try:
        rows = _iter_trades_since(trades_repo, since_ms, symbol)
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
    except Exception:
        logger.exception("realized_pnl_since_ms failed (since_ms=%s, symbol=%s)", since_ms, symbol)
        return 0.0


def risk_daily_loss_blocked(
    *,
    trades_repo: Any,
    daily_loss_limit_pct: float,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Блокируем торговлю при превышении дневного лимита потерь (% от базы).
    Ошибки — лог и мягкий отказ (blocked=True).
    """
    try:
        now = int(time.time() * 1000)
        start_of_day_ms = now - (now % (24 * 60 * 60 * 1000))

        realized = realized_pnl_since_ms(trades_repo=trades_repo, since_ms=start_of_day_ms, symbol=symbol)

        base_capital_usd = 0.0
        # если где-то задан базовый капитал — используем
        if hasattr(trades_repo, "base_capital_usd"):
            try:
                base_capital_usd = float(getattr(trades_repo, "base_capital_usd", 0.0))
            except Exception:
                base_capital_usd = 0.0

        if base_capital_usd > 0.0:
            pct = (realized / base_capital_usd) * 100.0
            limit_hit = pct <= -abs(float(daily_loss_limit_pct))
        else:
            # без знания базы — консервативнее: если лимит <= 0 и уже есть убыток — блокируем
            limit_hit = (float(daily_loss_limit_pct) <= 0.0) and (realized < 0.0)

        if limit_hit:
            return {"blocked": True, "reason": "daily_loss_limit_exceeded", "realized_pnl": realized}

        return {"blocked": False, "reason": None, "realized_pnl": realized}

    except Exception:
        logger.exception("risk_daily_loss_blocked failed (symbol=%s)", symbol)
        return {"blocked": True, "reason": "risk_internal_error"}
