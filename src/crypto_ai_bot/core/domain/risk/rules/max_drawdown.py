from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MaxDrawdownConfig:
    max_drawdown_pct: float  # 0 = отключено


class MaxDrawdownRule:
    """
    Внутридневная кумулятивная equity-линия из реализованного PnL (FIFO, с комиссиями).
    Блокирует, если относительная просадка от внутридневного пика >= max_drawdown_pct.
    """

    def __init__(self, cfg: MaxDrawdownConfig) -> None:
        self.cfg = cfg

    @staticmethod
    def _to_dec(x: Any) -> Decimal:
        return Decimal(str(x if x is not None else "0"))

    def _iter_today_asc(self, trades_repo: Any, symbol: str) -> list[Any]:
        # Нужна последовательность за "сегодня" в порядке времени
        if hasattr(trades_repo, "list_today"):
            rows = list(reversed(trades_repo.list_today(symbol)))  # type: ignore[attr-defined]
            return rows
        return []

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        lim_pct = float(self.cfg.max_drawdown_pct or 0.0)
        if lim_pct <= 0:
            return True, "disabled", {}

        rows = self._iter_today_asc(trades_repo, symbol)
        if not rows:
            return True, "no_today_trades", {}

        # FIFO склад покупок
        buy_lots: list[tuple[Decimal, Decimal]] = []
        cum: Decimal = Decimal("0")
        peak: Decimal = Decimal("0")
        worst_dd_pct: float = 0.0

        for r in rows:
            side = (r["side"] or "").lower()
            filled = self._to_dec(r.get("filled") or r.get("amount"))
            price = self._to_dec(r.get("price"))
            cost = self._to_dec(r.get("cost"))
            fee_q = self._to_dec(r.get("fee_quote"))

            if filled <= 0:
                continue

            if side == "buy":
                unit_cost = (cost + fee_q) / filled if filled > 0 else Decimal("0")
                buy_lots.append((filled, unit_cost))
                continue

            if side == "sell":
                qty = filled
                unit_sell = price
                realized = Decimal("0")
                i = 0
                while qty > 0 and i < len(buy_lots):
                    lot_qty, lot_uc = buy_lots[i]
                    take = min(lot_qty, qty)
                    realized += take * (unit_sell - lot_uc)
                    new_qty = lot_qty - take
                    qty -= take
                    if new_qty > 0:
                        buy_lots[i] = (new_qty, lot_uc)
                        i += 1
                    else:
                        buy_lots.pop(i)
                realized -= fee_q  # комиссия продажи

                cum += realized
                if cum > peak:
                    peak = cum
                # относительная просадка от пика
                denom = float(peak) if float(peak) != 0.0 else 1.0
                dd_pct = max(0.0, float(peak - cum) / abs(denom) * 100.0)
                worst_dd_pct = max(worst_dd_pct, dd_pct)
                if dd_pct >= lim_pct:
                    return (
                        False,
                        "max_drawdown",
                        {
                            "drawdown_pct": round(dd_pct, 6),
                            "limit_pct": lim_pct,
                        },
                    )

        return True, "ok", {"drawdown_pct": round(worst_dd_pct, 6), "limit_pct": lim_pct}
