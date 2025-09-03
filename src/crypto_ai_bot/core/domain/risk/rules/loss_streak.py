from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class LossStreakConfig:
    limit: int  # 0 = отключено


class LossStreakRule:
    """
    Считает ПОДРЯД идущие убыточные продажи (реализованный PnL < 0) по FIFO.
    История берётся вся (символ-локальная), комиссии учитываются через fee_quote.
    Если streak >= limit -> блок.
    """

    def __init__(self, cfg: LossStreakConfig) -> None:
        self.cfg = cfg

    @staticmethod
    def _to_dec(x: Any) -> Decimal:
        return Decimal(str(x if x is not None else "0"))

    def _iter_all_asc(self, trades_repo: Any, symbol: str) -> list[Any]:
        # Требуется API, возвращающий все трейды по символу в порядке возрастания времени.
        # В твоём TradesRepository есть аналогичный приватный итератор — реализуем локально через SQL в самом репозитории.
        if hasattr(trades_repo, "_iter_all_asc"):
            return trades_repo._iter_all_asc(symbol)  # type: ignore[attr-defined]
        # fallback: если нет — используем list_today + оставим как минимум за сегодня
        if hasattr(trades_repo, "list_today"):
            rows = trades_repo.list_today(symbol)  # type: ignore[attr-defined]
            return list(reversed(rows))  # приблизим к ASC
        return []

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        lim = int(self.cfg.limit or 0)
        if lim <= 0:
            return True, "disabled", {}

        rows = self._iter_all_asc(trades_repo, symbol)
        if not rows:
            return True, "no_trades", {}

        # FIFO склад покупок: [(qty_left, unit_cost_quote)]
        buy_lots: list[tuple[Decimal, Decimal]] = []
        streak = 0
        worst_trade_pnl: Decimal = Decimal("0")

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

                # комиссия продажи относится к этой продаже целиком
                realized -= fee_q
                if realized < 0:
                    streak += 1
                    if realized < worst_trade_pnl:
                        worst_trade_pnl = realized
                else:
                    streak = 0

                if streak >= lim:
                    return (
                        False,
                        "loss_streak",
                        {
                            "streak": streak,
                            "limit": lim,
                            "worst_trade_pnl": str(worst_trade_pnl),
                        },
                    )

        return True, "ok", {"streak": streak, "limit": lim}
