from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.risk import manager as risk_manager
from crypto_ai_bot.core.positions.tracker import build_context

def _calc_spread_pct_from_ticker(t: Dict[str, Any]) -> Optional[float]:
    """
    Пытаемся оценить спред по данным тикера.
    Ожидаем ключи: bid, ask, last/close/price. Возвращаем % (0..100).
    """
    if not isinstance(t, dict):
        return None
    bid = t.get("bid"); ask = t.get("ask")
    px = t.get("last", t.get("close", t.get("price")))
    try:
        bid = float(bid) if bid is not None else None
        ask = float(ask) if ask is not None else None
        px = float(px) if px is not None else None
    except Exception:
        return None
    # варианты
    if ask and bid and ask > 0 and bid > 0:
        mid = (ask + bid) / 2.0
        if mid > 0:
            return (ask - bid) / mid * 100.0
    if px and ask and px > 0 and ask > 0:
        return (ask - px) / px * 100.0
    if px and bid and px > 0 and bid > 0:
        return (px - bid) / px * 100.0
    return None

def eval_and_execute(cfg, broker, *, symbol: Optional[str] = None, timeframe: Optional[str] = None, limit: int = 300, **repos) -> Dict[str, Any]:
    """
    Полный цикл:
      1) Сбор контекста (PnL/позиции/экспозиция/время/маркет) + спред-стаб при необходимости
      2) Risk check → при блокировке возвращаем SKIPPED (без вызова place_order)
      3) evaluate() → получить Decision (прокидываем risk_reason в explain.blocks.risk при блокировке)
      4) place_order() → исполнение и запись в БД/аудит (если не заблокировано)
    """
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME

    # 1) Контекст
    summary = build_context(cfg, broker,
                            positions_repo=repos.get("positions_repo"),
                            trades_repo=repos.get("trades_repo"))

    # Попробуем дополнить market.spread_pct, если его нет
    market = summary.setdefault("market", {})
    if "spread_pct" not in market or market.get("spread_pct") is None:
        try:
            t = broker.fetch_ticker(sym)
            sp = _calc_spread_pct_from_ticker(t)
            if sp is not None:
                market["spread_pct"] = sp
        except Exception:
            pass

    # 2) Риск
    risk_ok, risk_reason = risk_manager.check(summary, cfg)

    # 3) Решение
    decision = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit,
                        risk_reason=(None if risk_ok else risk_reason), **repos)

    # Если риск блокирует — прекращаем
    if not risk_ok:
        return {
            "status": "skipped",
            "symbol": sym,
            "timeframe": tf,
            "reason": risk_reason,
            "decision": decision,
        }

    # 4) Исполнение (идемпотентность реализована внутри place_order)
    res = place_order(cfg, broker,
                      repos.get("positions_repo"),
                      repos.get("audit_repo"),
                      decision)
    out = {"status": "executed", "symbol": sym, "timeframe": tf, "decision": decision}
    if isinstance(res, dict):
        out.update(res)
    return out
