# src/crypto_ai_bot/core/signals/_fusion.py
"""
Fusion-функции: сбор простых фич (например, last_price, rsi, ma) и принятие решения.
Сигнатуры выдержаны так, чтобы спокойно принимать "лишние" kwargs (универсальность).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


Explain = Dict[str, Any]


async def build(
    symbol: str,
    *,
    cfg,
    positions_repo=None,
    external: Optional[Dict[str, Any]] = None,
    **_ignored,  # <- позволяет вызывать с broker=..., не ломая сигнатуру
) -> Dict[str, Any]:
    """
    Минимальный набор: last_price + признак есть_ли_лонг.
    Все внешние сетевые обращения совершайте СНАРУЖИ и пробрасывайте в external.
    """
    last_price = None
    if external and "ticker" in external:
        t = external["ticker"]
        last_price = float(t.get("last") or t.get("close") or 0.0)

    have_long = False
    if positions_repo:
        pos = positions_repo.get(symbol)
        have_long = bool(pos and float(pos.get("qty", 0.0)) > 0.0)

    return {
        "symbol": symbol,
        "last_price": last_price,
        "have_long": have_long,
    }


async def decide(
    features: Dict[str, Any],
    *,
    cfg,
) -> Dict[str, Any]:
    """
    Тупой базовый policy: если нет лонга — разрешаем BUY; если есть — разрешаем SELL.
    В реальности сюда добавляются RSI/MA/ATR и пороги из Settings.
    """
    have_long = bool(features.get("have_long", False))
    if not have_long:
        return {"action": "buy", "explain": {"reason": "no_long"}}
    return {"action": "sell", "explain": {"reason": "have_long"}}
