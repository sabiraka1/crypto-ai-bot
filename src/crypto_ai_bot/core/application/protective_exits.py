from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import BrokerPort, OrderSide, PositionDTO  # type: ignore
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("protective_exits")


# ----------------------------- Config -----------------------------

@dataclass(frozen=True)
class AtrExitConfig:
    atr_period: int = 14
    tp1_atr: Decimal = dec("1.0")
    tp2_atr: Decimal = dec("2.0")
    sl_atr: Decimal = dec("1.5")
    tp1_close_pct: int = 50              # сколько закрыть на TP1 (в процентах от позиции)
    enable_breakeven: bool = True        # подтягивать SL к breakeven после TP1
    min_base_to_exit: Decimal = dec("0") # не закрывать, если меньше минимального количества
    tick_interval_sec: float = 2.0       # период обновления

    def clamp(self) -> "AtrExitConfig":
        # лёгкая страховка от странных значений
        tp1 = max(dec("0"), self.tp1_atr)
        tp2 = max(tp1, self.tp2_atr)  # tp2 не меньше tp1
        sl = max(dec("0"), self.sl_atr)
        pct = min(100, max(0, int(self.tp1_close_pct)))
        return AtrExitConfig(
            atr_period=max(1, self.atr_period),
            tp1_atr=tp1,
            tp2_atr=tp2,
            sl_atr=sl,
            tp1_close_pct=pct,
            enable_breakeven=bool(self.enable_breakeven),
            min_base_to_exit=max(dec("0"), self.min_base_to_exit),
            tick_interval_sec=max(0.2, float(self.tick_interval_sec)),
        )


def _safe_dec(settings: Any, name: str, default: str) -> Decimal:
    try:
        raw = getattr(settings, name, default)
        if raw is None or raw == "":
            raw = default
        return dec(str(raw))
    except Exception:
        return dec(default)


def _cfg_from_settings(s: Any) -> AtrExitConfig:
    return AtrExitConfig(
        atr_period=int(getattr(s, "EXITS_ATR_PERIOD", 14) or 14),
        tp1_atr=_safe_dec(s, "EXITS_TP1_ATR", "1.0"),
        tp2_atr=_safe_dec(s, "EXITS_TP2_ATR", "2.0"),
        sl_atr=_safe_dec(s, "EXITS_SL_ATR", "1.5"),
        tp1_close_pct=int(getattr(s, "EXITS_TP1_CLOSE_PCT", 50) or 50),
        enable_breakeven=bool(int(getattr(s, "EXITS_ENABLE_BREAKEVEN", 1) or 1)),
        min_base_to_exit=_safe_dec(s, "EXITS_MIN_BASE", "0"),
        tick_interval_sec=float(getattr(s, "EXITS_TICK_INTERVAL_SEC", 2.0) or 2.0),
    ).clamp()


# ----------------------------- Helpers -----------------------------

def _ticker_last(t: Any) -> Decimal:
    """
    Достаёт «последнюю» цену из TickerDTO-подобного объекта или Mapping.
    Порядок приоритета: last -> bid -> ask.
    """
    val: Optional[Any] = None
    # Объектный путь
    val = getattr(t, "last", None) or getattr(t, "bid", None) or getattr(t, "ask", None)
    if val is not None:
        return dec(str(val))
    # Mapping путь
    if isinstance(t, Mapping):
        val = t.get("last") or t.get("bid") or t.get("ask")
        if val is not None:
            return dec(str(val))
    return dec("0")


def _position_size(pos: PositionDTO | Any) -> Decimal:
    """
    Унифицированно достаём размер позиции (base quantity).
    Пытаемся: .amount -> .size -> .qty -> 0
    """
    for name in ("amount", "size", "qty", "quantity"):
        if hasattr(pos, name):
            try:
                return dec(str(getattr(pos, name)))
            except Exception:
                pass
    return dec("0")


def _position_entry(pos: PositionDTO | Any) -> Decimal:
    """
    Унифицированно достаём цену входа.
    Пытаемся: .entry_price -> .avg_entry_price -> .price -> 0
    """
    for name in ("entry_price", "avg_entry_price", "price"):
        if hasattr(pos, name):
            try:
                return dec(str(getattr(pos, name)))
            except Exception:
                pass
    return dec("0")


# ----------------------------- Core -----------------------------

class ProtectiveExits:
    """
    Простой оркестратор защитных выходов по ATR:
      - TP1 = entry + tp1_atr * ATR  (частичное закрытие tp1_close_pct %)
      - TP2 = entry + tp2_atr * ATR  (закрытие остатка)
      - SL  = entry - sl_atr  * ATR  (полное закрытие)
      - Breakeven: после TP1 подтягивает SL к цене входа (если включено)
    """
    def __init__(self, *, broker: BrokerPort, storage: Any, bus: Any, settings: Any):
        self._broker: BrokerPort = broker
        self._storage: Any = storage
        self._bus: Any = bus
        self._cfg: AtrExitConfig = _cfg_from_settings(settings)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ---------- lifecycle ----------

    async def start(self, symbol: str) -> None:
        if symbol in self._tasks and not self._tasks[symbol].done():
            return
        self._tasks[symbol] = asyncio.create_task(self._loop(symbol), name=f"protective-{symbol}")
        await self._bus.publish(EVT.ORCH_STARTED, {"symbol": symbol, "component": "protective_exits"})

    async def stop(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            return

        t = self._tasks.pop(symbol, None)
        if t:
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)

    # ---------- loop ----------

    async def _loop(self, symbol: str) -> None:
        try:
            while True:
                try:
                    res = await self._evaluate_once(symbol)
                    if res:
                        await self._bus.publish(EVT.ORCH_TICK, {"symbol": symbol, **res})
                    # если позиция закрыта — выходим из цикла
                    if res and res.get("all_closed") is True:
                        _log.info("exits_loop_stop_all_closed", extra={"symbol": symbol})
                        break
                except Exception:
                    _log.error("exits_loop_iteration_failed", extra={"symbol": symbol}, exc_info=True)
                await asyncio.sleep(self._cfg.tick_interval_sec)
        except asyncio.CancelledError:
            pass
        finally:
            self._tasks.pop(symbol, None)

    # ---------- evaluation ----------

    async def _evaluate_once(self, symbol: str) -> dict[str, Any] | None:
        """Выполнить оценку условий выхода один раз для symbol."""
        pos = self._get_position(symbol)
        if not pos:
            return {"status": "no_position", "all_closed": True}

        size = _position_size(pos)
        if size <= dec("0"):
            return {"status": "empty_position", "all_closed": True}

        entry = _position_entry(pos)
        if entry <= dec("0"):
            _log.warning("position_entry_zero", extra={"symbol": symbol})
            return None

        # Тикер
        try:
            t = await self._broker.fetch_ticker(symbol)
            last = _ticker_last(t)
        except Exception:
            _log.error("ticker_fetch_failed", extra={"symbol": symbol}, exc_info=True)
            return None

        if last <= dec("0"):
            return None

        # ATR
        atr = await self._atr(symbol, period=self._cfg.atr_period)
        if atr <= dec("0"):
            return None

        tp1 = entry + self._cfg.tp1_atr * atr
        tp2 = entry + self._cfg.tp2_atr * atr
        sl  = entry - self._cfg.sl_atr  * atr

        # Breakeven: если цена прошла TP1 (и включено) — SL = entry
        use_breakeven = self._cfg.enable_breakeven and last >= tp1
        if use_breakeven and sl < entry:
            sl = entry

        # Логика исполнения
        all_closed = False
        fired: list[str] = []

        # Stop-Loss
        if last <= sl:
            ok = await self._sell(symbol, size, reason="SL")
            inc("protective.exit.sl", symbol=symbol)
            fired.append("SL")
            all_closed = ok
            return {"status": "sl", "price": str(last), "all_closed": all_closed}

        # TP2 — закрываем остаток
        if last >= tp2:
            ok = await self._sell(symbol, size, reason="TP2")
            inc("protective.exit.tp2", symbol=symbol)
            fired.append("TP2")
            all_closed = ok
            return {"status": "tp2", "price": str(last), "all_closed": all_closed}

        # TP1 — частичное закрытие
        if last >= tp1:
            qty = (size * Decimal(self._cfg.tp1_close_pct) / Decimal(100)).quantize(dec("0.00000001"))
            qty = max(qty, dec("0"))
            if qty >= self._cfg.min_base_to_exit and qty > dec("0"):
                ok = await self._sell(symbol, qty, reason="TP1")
                inc("protective.exit.tp1", symbol=symbol)
                fired.append("TP1")
                return {"status": "tp1", "qty": str(qty), "price": str(last), "all_closed": False}

        return {"status": "hold", "price": str(last), "fired": fired or None, "all_closed": False}

    # ---------- ATR ----------

    async def _atr(self, symbol: str, *, period: int) -> Decimal:
        """
        Простой ATR(period) по TR = max(high-low, |high-close_prev|, |low-close_prev|)
        OHLCV из брокера: List[Tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]
        """
        try:
            rows = await self._broker.fetch_ohlcv(symbol, timeframe="1h", limit=max(2, period + 1))
        except Exception:
            _log.error("ohlcv_fetch_failed", extra={"symbol": symbol}, exc_info=True)
            return dec("0")

        if not rows or len(rows) < 2:
            return dec("0")

        # Собираем (o,h,l,c) и считаем TR
        prev_close: Optional[Decimal] = None
        trs: list[Decimal] = []

        for row in rows:
            # Приводим: ts, o, h, l, c, v
            try:
                ts, o, h, l, c, v = row  # ts может быть datetime
            except Exception:
                # На случай если приходят 5 значений (без volume)
                ts, o, h, l, c = row[:5]

            O = dec(str(o)); H = dec(str(h)); L = dec(str(l)); C = dec(str(c))

            if prev_close is None:
                tr = H - L
            else:
                tr = max(H - L, abs(H - prev_close), abs(L - prev_close))
            trs.append(tr)
            prev_close = C

        if not trs:
            return dec("0")

        # простой средний ATR последних `period` TR (без EMA, как и было в исходнике)
        tail = trs[-period:]
        atr = sum(tail, start=dec("0")) / Decimal(len(tail))
        return atr

    # ---------- side-effects ----------

    def _get_position(self, symbol: str) -> Optional[PositionDTO | Any]:
        """
        Унифицированный доступ к позиции из storage:
        допускаются методы: get_position(symbol) или positions.get(symbol)
        """
        # метод get_position()
        if hasattr(self._storage, "get_position"):
            try:
                return self._storage.get_position(symbol)  # type: ignore[no-any-return]
            except Exception:
                pass
        # словарь positions
        if hasattr(self._storage, "positions"):
            try:
                return getattr(self._storage, "positions").get(symbol)  # type: ignore[attr-defined]
            except Exception:
                pass
        return None

    async def _sell(self, symbol: str, qty: Decimal, *, reason: str) -> bool:
        """
        Унифицированное «продать qty» для защитных выходов.
        Отправляет события и пишет логи.
        """
        if qty <= dec("0"):
            return True
        try:
            await self._bus.publish(EVT.ORDER_CREATED, {"symbol": symbol, "side": "sell", "reason": reason, "amount": str(qty)})
            order = await self._broker.create_market_order(symbol, OrderSide.SELL, qty, client_order_id=f"protective_{reason.lower()}")
            await self._bus.publish(
                EVT.TRADE_COMPLETED,
                {"symbol": symbol, "side": "sell", "reason": reason, "amount": str(qty), "order_id": getattr(order, "id", None)},
            )
            _log.info("protective_exit_sell_qty", extra={"symbol": symbol, "qty": str(qty), "reason": reason})
            return True
        except Exception as exc:
            await self._bus.publish(EVT.TRADE_FAILED, {"symbol": symbol, "side": "sell", "reason": str(exc)})
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(exc)})
            return False


# ----------------------------- Factory -----------------------------

def make_protective_exits(*, broker: BrokerPort, storage: Any, bus: Any, settings: Any) -> ProtectiveExits:
    """Factory function for creating ProtectiveExits."""
    return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)
