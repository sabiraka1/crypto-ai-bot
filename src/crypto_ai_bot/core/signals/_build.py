## `core/signals/_build.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List
from ..storage.facade import Storage
@dataclass(frozen=True)
class BuiltFeatures:
    last: Decimal
    sma_n: Decimal
    ema_n: Decimal
    spread_pct: float
def _ema(values: List[Decimal], alpha: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (Decimal("1") - alpha) * ema
    return ema
def build_features(*, symbol: str, storage: Storage, n: int = 20) -> Dict[str, object]:
    """Строит базовые признаки по последним N снапшотам из ticker_snapshots.
    Возвращает dict, совместимый с evaluate().
    """
    rows = storage.market_data.get_last_ticker(symbol)
    conn = storage.conn
    cur = conn.execute(
        "SELECT last, bid, ask FROM ticker_snapshots WHERE symbol=? ORDER BY ts_ms DESC LIMIT ?",
        (symbol, n),
    )
    vals = cur.fetchall()
    if not vals:
        return {"last": "0", "sma": "0", "ema": "0", "spread_pct": 0.0}
    lasts = [Decimal(str(v[0])) for v in reversed(vals)]
    bids = [Decimal(str(v[1])) for v in reversed(vals)]
    asks = [Decimal(str(v[2])) for v in reversed(vals)]
    last = lasts[-1]
    sma = (sum(lasts) / Decimal(len(lasts))).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    alpha = Decimal("2") / Decimal(n + 1)
    ema = _ema(lasts, alpha).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    bid = bids[-1]
    ask = asks[-1]
    mid = (bid + ask) / Decimal("2") if (bid > 0 and ask > 0) else last
    spread_pct = float(((ask - bid) / mid) * Decimal("100")) if mid > 0 else 0.0
    return {
        "last": str(last),
        "sma": str(sma),
        "ema": str(ema),
        "spread_pct": spread_pct,
    }