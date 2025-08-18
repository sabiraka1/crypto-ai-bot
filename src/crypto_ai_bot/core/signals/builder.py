# src/crypto_ai_bot/core/signals/builder.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from crypto_ai_bot.core.brokers.symbols import normalize_symbol

logger = logging.getLogger("signals.builder")


def _safe(callable_, name: str, ctx_errors: list) -> Optional[float]:
    try:
        return float(callable_())
    except Exception as e:
        logger.exception("feature '%s' failed: %s", name, e)
        ctx_errors.append({"feature": name, "error": repr(e)})
        return None


def build(
    symbol: str,
    *,
    cfg: Any,
    broker: Any,
    positions_repo: Optional[Any] = None,
    external: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Единая точка построения features/context.
    - Внутренние метрики (кол-во позиций, нотационал) считаются безопасно.
    - Внешние индикаторы (btc_dominance/fear_greed/dxy) — по возможности.
    - Все исключения попадают в context['errors'] и в логи.
    """
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    ctx_errors: list = []

    # ---- features из рыночных данных (минимум для примера) ----
    def _last():
        t = broker.fetch_ticker(sym)
        return t.get("last") or t.get("close") or 0.0

    last = _safe(_last, "last_price", ctx_errors)

    # ---- внешние индикаторы (если переданы) ----
    ext = external or {}
    btc_dominance = None
    fear_greed = None
    dxy = None
    if "btc_dominance" in ext:
        btc_dominance = _safe(lambda: ext["btc_dominance"], "btc_dominance", ctx_errors)
    if "fear_greed" in ext:
        fear_greed = _safe(lambda: ext["fear_greed"], "fear_greed", ctx_errors)
    if "dxy" in ext:
        dxy = _safe(lambda: ext["dxy"], "dxy", ctx_errors)

    # ---- внутренние метрики по позициям ----
    open_positions = 0
    open_notional = 0.0
    if positions_repo is not None:
        try:
            rows = positions_repo.get_open()
            open_positions = len(rows)
            if last:
                for r in rows:
                    qty = float(r.get("qty") or 0.0)
                    open_notional += qty * float(last or 0.0)
        except Exception as e:
            logger.exception("positions_repo.get_open failed: %s", e)
            ctx_errors.append({"feature": "positions_open", "error": repr(e)})

    features = {
        "last": last,
        "btc_dominance": btc_dominance,
        "fear_greed": fear_greed,
        "dxy": dxy,
    }

    context = {
        "symbol": sym,
        "open_positions": open_positions,
        "open_notional": float(open_notional),
        "errors": ctx_errors,
    }

    return {"features": features, "context": context}
