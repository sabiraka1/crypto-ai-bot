from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application import events_topics as EVT  # noqa: N812
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("protective_exits")

# ----------------------------- Сё  СјС°СЋ -----------------------------


@dataclass(frozen=True)
class AtrExitConfig:
    atr_period: int = 14  # Сё ATR
    tp1_atr: Decimal = dec("1.0")  # TP1 = entry + 1.0 * ATR
    tp2_atr: Decimal = dec("2.0")  # TP2 = entry + 2.0 * ATR
    sl_atr: Decimal = dec("1.5")  # SL  = entry - 1.5 * ATR
    tp1_close_pct: int = 50  # СѕСµ Сё, СІС№  TP1
    enable_breakeven: bool = True  # СµСЃ SL  / СЃ TP1
    min_base_to_exit: Decimal = dec("0")  #  СІ СѕСµСЅСµ Сј
    tick_interval_sec: float = 2.0  # Сё Сѕ СѕСє
    ohlcv_limit: int = 200  # СЃСё  С·
    timeframe: str = "15m"  # С°Сё TF


def _safe_dec(settings: Any, name: str, default: str) -> Decimal:
    val = getattr(settings, name, None)
    if val is None:
        return dec(default)
    try:
        s = str(val).strip()
        if not s or s.lower() in ("none", "null"):
            return dec(default)  # noqa: TRY300
        float(s)
        return dec(s)  # noqa: TRY300
    except Exception:  # noqa: BLE001
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
        ohlcv_limit=int(getattr(s, "STRAT_OHLCV_LIMIT", 200) or 200),
        timeframe=str(getattr(s, "STRAT_TIMEFRAME", "15m") or "15m"),
    )


# ------------------------------- ATR Сё -----------------------------------


def _true_ranges(ohlcv: list[list[Decimal]]) -> list[Decimal]:
    # ohlcv: [ts, open, high, low, close, volume]
    if not ohlcv or len(ohlcv) < 2:
        return []
    trs: list[Decimal] = []
    prev_close = dec(str(ohlcv[0][4]))
    for row in ohlcv[1:]:
        high = dec(str(row[2]))
        low = dec(str(row[3]))
        close = dec(str(row[4]))
        tr = max(high - low, abs(high - prev_close), abs(prev_close - low))
        trs.append(tr)
        prev_close = close
    return trs


def _ema_last(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period:
        return None
    k = dec("2") / dec(str(period + 1))
    ema = values[0]
    for x in values[1:]:
        ema = x * k + ema * (dec("1") - k)
    return ema


async def _atr(broker: Any, symbol: str, timeframe: str, limit: int, period: int) -> Decimal | None:
    try:
        ohlcv_raw = await broker.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv_raw:
            return None  # noqa: TRY300
        # СµС°  Decimal
        ohlcv: list[list[Decimal]] = []
        for r in ohlcv_raw:
            ohlcv.append(
                [
                    dec(str(r[0])),
                    dec(str(r[1])),
                    dec(str(r[2])),
                    dec(str(r[3])),
                    dec(str(r[4])),
                    dec(str(r[5])),
                ]
            )
        trs = _true_ranges(ohlcv)
        if len(trs) < period:
            return None
        return _ema_last(trs, period)
    except Exception:  # noqa: BLE001
        _log.error("atr_fetch_failed", extra={"symbol": symbol, "tf": timeframe}, exc_info=True)
        return None


# ------------------------------- СЃ СЃСЃ --------------------------------


class ProtectiveExits:
    """
    ATR-Сѕ СЏ LONG-Сё:
      - TP1 = +tp1_atr*ATR ( tp1_close_pct, СµСЃ SL  /)
      - TP2 = +tp2_atr*ATR ( СЃС°Сѕ)
      - SL  = -sl_atr*ATR
    СЏ С»СЏ  СЃ СЃСЃСЏ СЃ BUY СµСµ on_hint().
    """

    def __init__(self, *, broker: Any, storage: Any, bus: Any, settings: Any) -> None:
        self._broker = broker
        self._storage = storage
        self._bus = bus
        self._settings = settings
        self._cfg = _cfg_from_settings(settings)

        # СЃСЃСѕСЏ  СЃ
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._tp1_done: dict[str, bool] = {}  # TP1 Сѕ
        self._breakeven_px: dict[str, Decimal] = {}  # Сµ / СЃ TP1

    # API СЃСЃСёСЃСё (СєСЃС°Сѕ  Сѕ)
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for sym, t in list(self._tasks.items()):
            t.cancel()
            self._tasks.pop(sym, None)

    # ---- СЃСёСЏ/СЃ  Сё (compose С¶ СЃСІ trade.completed) ----
    async def on_hint(self, evt: dict[str, Any]) -> None:
        """
        С° trade.completed; СЃ СЌСѕ BUY  СЃС°Сµ СѕС№ Сѕ,
        СЃ SELL  Сё Сµ   СЃСѕ Сѕ.
        """
        sym = str(evt.get("symbol", "") or "")
        if not sym:
            return
        side = str(evt.get("side", evt.get("action", "") or "")).lower()

        if side == "buy":
            # СЃСѕСЃ СЃСЃСѕСЏСЏ  СЃС° Сѕ СѕСё
            self._tp1_done[sym] = False
            self._breakeven_px.pop(sym, None)
            await self._ensure_task(sym)
        elif side == "sell":
            # СЃ Сё   СЃС°
            pos = self._storage.positions.get_position(sym) if hasattr(self._storage, "positions") else None
            if not pos or (getattr(pos, "base_qty", dec("0")) or dec("0")) <= 0:
                self._cancel_task(sym)

    # ---- С±СЅСµ СµСµСЃ (СЃС°СЏ СЃ) ----
    async def evaluate(self, *, symbol: str) -> dict[str, Any] | None:
        """С°СЏ Сµ ( С·СІ СЅСЋ)."""
        return await self._evaluate_once(symbol)

    async def tick(self, symbol: str) -> dict[str, Any] | None:
        """СЃСёСЃ: Сµ  evaluate()."""
        return await self.evaluate(symbol=symbol)

    # ------------------------------ СµСЏСЏ  ---------------------------

    def _cancel_task(self, symbol: str) -> None:
        t = self._tasks.pop(symbol, None)
        if t:
            t.cancel()

    async def _ensure_task(self, symbol: str) -> None:
        if symbol in self._tasks and not self._tasks[symbol].done():
            return
        self._tasks[symbol] = asyncio.create_task(self._loop(symbol))
        _log.info("exits_loop_started", extra={"symbol": symbol})

    async def _loop(self, symbol: str) -> None:
        try:
            while True:
                try:
                    res = await self._evaluate_once(symbol)
                    if res and res.get("closed_all"):
                        _log.info("exits_loop_stop_all_closed", extra={"symbol": symbol})
                        break
                except Exception:  # noqa: BLE001
                    _log.error("exits_loop_iteration_failed", extra={"symbol": symbol}, exc_info=True)
                await asyncio.sleep(self._cfg.tick_interval_sec)
        except asyncio.CancelledError:
            pass
        finally:
            self._tasks.pop(symbol, None)

    async def _evaluate_once(self, symbol: str) -> dict[str, Any] | None:
        # СёСЏ
        pos = self._storage.positions.get_position(symbol) if hasattr(self._storage, "positions") else None
        if not pos:
            return None

        base = getattr(pos, "base_qty", dec("0")) or dec("0")
        entry = getattr(pos, "avg_entry_price", dec("0")) or dec("0")
        if base <= 0 or entry <= 0:
            return None

        # Сё
        try:
            t = await self._broker.fetch_ticker(symbol)
            last = dec(str(t.get("last") or t.get("bid") or t.get("ask") or "0"))
        except Exception as e:  # noqa: BLE001
            _log.warning("ticker_fetch_failed", extra={"symbol": symbol, "error": str(e)})
            return None  # noqa: TRY300
        if last <= 0:
            return None

        # ATR
        atr = await _atr(
            self._broker, symbol, self._cfg.timeframe, self._cfg.ohlcv_limit, self._cfg.atr_period
        )
        if atr is None or atr <= 0:
            inc("protective_exits_tick_total", symbol=symbol, reason="no_atr")
            return None

        # Сѕ
        tp1_px = entry + self._cfg.tp1_atr * atr
        tp2_px = entry + self._cfg.tp2_atr * atr
        sl_px = entry - self._cfg.sl_atr * atr

        # breakeven СЃ TP1
        if (
            self._tp1_done.get(symbol, False)
            and self._cfg.enable_breakeven
            and symbol not in self._breakeven_px
        ):
            self._breakeven_px[symbol] = entry

        # СµСµСЏ
        if last <= sl_px:
            return await self._sell_all(symbol, base, reason=f"SL_ATR({self._cfg.sl_atr}ATR)")

        if not self._tp1_done.get(symbol, False) and last >= tp1_px:
            # Сѕ С°СЃ
            part_pct = max(1, min(100, int(self._cfg.tp1_close_pct)))
            qty = (base * dec(str(part_pct))) / dec("100")
            if self._cfg.min_base_to_exit > 0 and qty < self._cfg.min_base_to_exit:
                return None
            ok = await self._sell_qty(symbol, qty, reason=f"TP1_{part_pct}%@{self._cfg.tp1_atr}ATR")
            if ok:
                self._tp1_done[symbol] = True
                if self._cfg.enable_breakeven:
                    self._breakeven_px[symbol] = entry
                #  СёСЋ
                pos = (
                    self._storage.positions.get_position(symbol)
                    if hasattr(self._storage, "positions")
                    else None
                )
                base = getattr(pos, "base_qty", dec("0")) or dec("0")
                if base <= 0:
                    self._cancel_task(symbol)
                    return {"closed_all": True, "side": "sell", "qty": "0", "reason": "tp1_all"}
                return {"closed_part": True, "side": "sell", "qty": str(qty), "reason": "tp1"}
            return None

        # breakeven
        if self._tp1_done.get(symbol, False) and self._cfg.enable_breakeven:
            be = self._breakeven_px.get(symbol, None)
            if be and last <= be:
                return await self._sell_all(symbol, base, reason="BREAKEVEN")

        if last >= tp2_px:
            return await self._sell_all(symbol, base, reason=f"TP2@{self._cfg.tp2_atr}ATR")

        inc("protective_exits_tick_total", symbol=symbol)
        return None

    async def _sell_all(self, symbol: str, base: Decimal, reason: str) -> dict[str, Any] | None:
        if self._cfg.min_base_to_exit > 0 and base < self._cfg.min_base_to_exit:
            return None
        try:
            await self._broker.create_market_sell_base(symbol=symbol, base_amount=base)
            await self._bus.publish(
                EVT.TRADE_COMPLETED, {"symbol": symbol, "side": "sell", "reason": reason, "amount": str(base)}
            )
            _log.info(
                "protective_exit_sell_all", extra={"symbol": symbol, "qty": str(base), "reason": reason}
            )
            self._cancel_task(symbol)
            return {"closed_all": True, "side": "sell", "qty": str(base), "reason": reason}  # noqa: TRY300
        except Exception as e:  # noqa: BLE001
            await self._bus.publish(EVT.TRADE_FAILED, {"symbol": symbol, "side": "sell", "reason": str(e)})
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(e)})
            return None

    async def _sell_qty(self, symbol: str, qty: Decimal, reason: str) -> bool:
        try:
            await self._broker.create_market_sell_base(symbol=symbol, base_amount=qty)
            await self._bus.publish(
                EVT.TRADE_COMPLETED, {"symbol": symbol, "side": "sell", "reason": reason, "amount": str(qty)}
            )
            _log.info("protective_exit_sell_qty", extra={"symbol": symbol, "qty": str(qty), "reason": reason})
            return True  # noqa: TRY300
        except Exception as e:  # noqa: BLE001
            await self._bus.publish(EVT.TRADE_FAILED, {"symbol": symbol, "side": "sell", "reason": str(e)})
            _log.error("protective_exit_failed", extra={"symbol": symbol, "error": str(e)})
            return False


def make_protective_exits(*, broker: Any, storage: Any, bus: Any, settings: Any) -> ProtectiveExits:
    return ProtectiveExits(broker=broker, storage=storage, bus=bus, settings=settings)
