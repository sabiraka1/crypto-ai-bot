from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.core.application.reconciliation.positions import compute_sell_amount
from crypto_ai_bot.core.application.reconciliation.positions import compute_sell_amount

_log = get_logger("protective_exits")


@dataclass(frozen=True)
class ExitConfig:
    stop_pct: Decimal = dec("0")
    take_pct: Decimal = dec("0")
    trailing_pct: Decimal = dec("0")
    min_base: Decimal = dec("0")


class ProtectiveExits:
    """
    SL/TP/Trailing только close-only для LONG.
    Шорты не открываются: продаём не больше текущей позиции.
    """
    def __init__(self, *, broker: Any, storage: Any, bus: Any, settings: Any) -> None:
        self._broker = broker
        self._storage = storage
        self._bus = bus
        self._settings = settings
        self._cfg = ExitConfig(
            stop_pct=dec(str(getattr(settings, "EXITS_STOP_PCT", "0") or "0")),
            take_pct=dec(str(getattr(settings, "EXITS_TAKE_PCT", "0") or "0")),
            trailing_pct=dec(str(getattr(settings, "EXITS_TRAIL_PCT", "0") or "0")),
            min_base=dec(str(getattr(settings, "EXITS_MIN_BASE", "0") or "0")),
        )

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def evaluate(self, *, symbol: str) -> dict | None:
        # Нет порогов — ничего не делаем
        if self._cfg.stop_pct <= 0 and self._cfg.take_pct <= 0 and self._cfg.trailing_pct <= 0:
            return None

        pos = self._storage.positions.get_position(symbol)
        if not pos:
            return None

        base = pos.base_qty or dec("0")
        avg = pos.avg_entry_price or dec("0")
        if base <= 0 or avg <= 0:
            return None

        try:
            t = await self._broker.fetch_ticker(symbol)
            last = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
        except Exception as e:
            _log.warning("ticker_fetch_failed", extra={"symbol": symbol, "error": str(e)})
            return None
        if last <= 0:
            return None

        stop_price = avg * (dec("1") - (self._cfg.stop_pct / dec("100"))) if self._cfg.stop_pct > 0 else None
        take_price = avg * (dec("1") + (self._cfg.take_pct / dec("100"))) if self._cfg.take_pct > 0 else None

        # Trailing
        trail_trigger = None
        if self._cfg.trailing_pct > 0:
            try:
                max_seen = getattr(pos, "max_price", None)
                if max_seen is None or last > max_seen:
                    max_seen = last
                    if hasattr(self._storage.positions, "update_max_price"):
                        self._storage.positions.update_max_price(symbol, max_seen)
                trail_trigger = max_seen * (dec("1") - (self._cfg.trailing_pct / dec("100")))
            except Exception:
                trail_trigger = last * (dec("1") - (self._cfg.trailing_pct / dec("100")))

        should_close = False
        reason = ""

        if stop_price and last <= stop_price:
            should_close = True
            reason = f"stop_loss@{self._cfg.stop_pct}%"
        if not should_close and take_price and last >= take_price:
            should_close = True
            reason = f"take_profit@{self._cfg.take_pct}%"
        if not should_close and trail_trigger and last <= trail_trigger:
            should_close = True
            reason = f"trailing_stop@{self._cfg.trailing_pct}%"

        if not should_close:
            inc("protective_exits_tick_total", symbol=symbol)
            return None

        # Продаём не больше, чем есть
        qty = base
        if self._cfg.min_base > 0 and qty < self._cfg.min_base:
            return None
        try:
            await self._broker.create_market_sell_base(symbol=symbol, base_amount=qty)
            await self._bus.publish("trade.completed", {"symbol": symbol, "action": "sell", "reason": reason, "amount": str(qty)})
            _log.info("protective_exit_sell", extra={"symbol": symbol, "qty": str(qty), "reason": reason})
            return {"closed": True, "qty": str(qty), "reason": reason}
        except Exception as e:
            await self._bus.publish("trade.failed", {"symbol": symbol, "action": "sell", "reason": str(e)})
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(e)})
            return None

    async def tick(self, symbol: str) -> dict | None:
        return await self.evaluate(symbol=symbol)


def make_protective_exits(*, broker: Any, storage: Any, bus: Any, settings: Any) -> ProtectiveExits:
    return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)