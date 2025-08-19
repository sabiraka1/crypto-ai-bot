from __future__ import annotations
from typing import Optional, Dict, Any, List
from decimal import Decimal

def _D(x) -> Decimal:
    return Decimal(str(x))

def ensure_protective_exits(
    cfg: Any,
    exits_repo: Any,
    positions_repo: Any,  # зарезервировано под расширения (валидаторы/контекст)
    *,
    symbol: str,
    entry_price: float,
    position_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Регистрирует soft SL/TP в БД для long-only позиции.
    Ожидается, что проценты заданы долей (напр., 0.02 = 2%).
    Исполнение делает оркестратор (tick_exits).

    Возвращает: {"created": [{"kind": "sl"|"tp", "trigger_px": float, "id": Any}, ...]}
    """
    created: List[Dict[str, Any]] = []
    price = _D(entry_price)

    sl_pct = getattr(cfg, "STOP_LOSS_PCT", None)
    if sl_pct:
        sl_px = float(price * (Decimal(1) - _D(sl_pct)))
        sl_id = exits_repo.upsert(
            position_id=position_id, symbol=symbol, side="sell", kind="sl", trigger_px=sl_px
        )
        created.append({"kind": "sl", "trigger_px": sl_px, "id": sl_id})

    tp_pct = getattr(cfg, "TAKE_PROFIT_PCT", None)
    if tp_pct:
        tp_px = float(price * (Decimal(1) + _D(tp_pct)))
        tp_id = exits_repo.upsert(
            position_id=position_id, symbol=symbol, side="sell", kind="tp", trigger_px=tp_px
        )
        created.append({"kind": "tp", "trigger_px": tp_px, "id": tp_id})

    return {"created": created}
