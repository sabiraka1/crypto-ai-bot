from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

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
        
        # Безопасное получение параметров с обработкой None и пустых строк
        def safe_dec(name: str, default: str = "0") -> Decimal:
            val = getattr(settings, name, None)
            if val is None:
                return dec(default)
            try:
                str_val = str(val).strip()
                # Проверяем на пустую строку или None
                if not str_val or str_val.lower() in ("none", "null", ""):
                    return dec(default)
                # Проверяем что это валидное число
                float(str_val)  # проверка на валидность
                return dec(str_val)
            except (ValueError, TypeError, AttributeError):
                return dec(default)
        
        # Поддержка разных имен параметров для совместимости
        stop_pct = safe_dec("EXITS_STOP_PCT", "0")
        if stop_pct == dec("0"):
            stop_pct = safe_dec("EXITS_HARD_STOP_PCT", "0")
        
        take_pct = safe_dec("EXITS_TAKE_PCT", "0")
        if take_pct == dec("0"):
            take_pct = safe_dec("EXITS_TAKE_PROFIT_PCT", "0")
        
        trailing_pct = safe_dec("EXITS_TRAIL_PCT", "0")
        if trailing_pct == dec("0"):
            trailing_pct = safe_dec("EXITS_TRAILING_PCT", "0")
        
        min_base = safe_dec("EXITS_MIN_BASE", "0")
        if min_base == dec("0"):
            min_base = safe_dec("EXITS_MIN_BASE_TO_EXIT", "0")
        
        self._cfg = ExitConfig(
            stop_pct=stop_pct,
            take_pct=take_pct,
            trailing_pct=trailing_pct,
            min_base=min_base,
        )

    async def start(self) -> None:
        """Start protective exits monitoring."""
        pass

    async def stop(self) -> None:
        """Stop protective exits monitoring."""
        pass

    async def evaluate(self, *, symbol: str) -> Optional[Dict[str, Any]]:
        """Evaluate if position should be closed."""
        # Нет порогов — ничего не делаем
        if self._cfg.stop_pct <= 0 and self._cfg.take_pct <= 0 and self._cfg.trailing_pct <= 0:
            return None

        pos = self._storage.positions.get_position(symbol)
        if not pos:
            return None

        base = getattr(pos, "base_qty", dec("0")) or dec("0")
        avg = getattr(pos, "avg_entry_price", dec("0")) or dec("0")
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

        stop_price: Optional[Decimal] = None
        take_price: Optional[Decimal] = None
        
        if self._cfg.stop_pct > 0:
            stop_price = avg * (dec("1") - (self._cfg.stop_pct / dec("100")))
        if self._cfg.take_pct > 0:
            take_price = avg * (dec("1") + (self._cfg.take_pct / dec("100")))

        # Trailing
        trail_trigger: Optional[Decimal] = None
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
        elif take_price and last >= take_price:
            should_close = True
            reason = f"take_profit@{self._cfg.take_pct}%"
        elif trail_trigger and last <= trail_trigger:
            should_close = True
            reason = f"trailing_stop@{self._cfg.trailing_pct}%"

        if not should_close:
            inc("protective_exits_tick_total", symbol=symbol)
            return None

        qty: Decimal = base
            
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

    async def tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Process tick for protective exits."""
        return await self.evaluate(symbol=symbol)

    async def on_hint(self, evt: Dict[str, Any]) -> None:
        """Handle hint events."""
        pass


def make_protective_exits(*, broker: Any, storage: Any, bus: Any, settings: Any) -> ProtectiveExits:
    """Factory function for creating ProtectiveExits instance."""
    return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)