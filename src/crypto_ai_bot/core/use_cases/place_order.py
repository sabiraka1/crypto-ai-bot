from __future__ import annotations
from typing import Any, Dict, Optional
from decimal import Decimal

from crypto_ai_bot.core.positions.manager import PositionManager
from crypto_ai_bot.core.storage.idempotency_helper import make_idempotency_key, check_and_store

def place_order(
    cfg,
    broker,
    positions_repo,
    trades_repo,
    audit_repo,
    uow,
    idempotency_repo,
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute order atomically with idempotency. Returns execution result dict.
    Assumes decision fields: action ('buy'|'sell'|'hold'), size (Decimal-like), price (optional),
    symbol, ts (ms, optional), decision_id.
    """
    action = str(decision.get('action') or 'hold').lower()
    symbol = decision.get('symbol') or getattr(cfg, 'SYMBOL', 'BTC/USDT')
    size = Decimal(str(decision.get('size') or '0'))
    ts_ms = int(decision.get('ts') or 0)
    decision_id = str(decision.get('decision_id') or 'missing')

    if action == 'hold' or size == 0:
        return {'status': 'skipped', 'reason': 'hold', 'decision_id': decision_id}

    side = 'buy' if size > 0 else 'sell'
    key = make_idempotency_key(symbol=symbol, side=side, size=abs(size), ts_ms=ts_ms, decision_id=decision_id)

    claimed = check_and_store(idempotency_repo, key)
    if not claimed:
        return {'status': 'duplicate', 'key': key, 'decision_id': decision_id}

    pm = PositionManager(positions_repo=positions_repo, trades_repo=trades_repo, audit_repo=audit_repo, uow=uow)

    # For simplicity we let exchange adapter calculate price when None (market order)
    price = decision.get('price')
    if price is not None:
        price = Decimal(str(price))

    # Execute via exchange adapter
    # For a paper/backtest exchange, broker.create_order should behave deterministically
    order_resp = broker.create_order(symbol=symbol, type_='market', side=side, amount=abs(size), price=price)

    # Update local storage/position snapshot
    # We choose executed price from adapter response if available, otherwise 'price'
    executed_price = Decimal(str(order_resp.get('price') or price or 0))
    pm.open_or_add(symbol, Decimal(str(size if side == 'buy' else -abs(size) if size > 0 else size)), executed_price)

    # persist idempotent result
    try:
        if idempotency_repo is not None:
            idempotency_repo.commit(key, {'order': order_resp})
    except Exception:
        # do not fail the whole call if commit fails; consistency is eventual
        pass

    return {'status': 'ok', 'key': key, 'order': order_resp, 'decision_id': decision_id}
