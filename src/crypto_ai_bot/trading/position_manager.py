# src/crypto_ai_bot/trading/position_manager.py
"""
💼 PositionManager — лёгкий продакшн-менеджер позиций (лонг-только)
Совместим с TradingBot: .open(ctx), .manage(price, atr), .close_all(price, reason)

Особенности:
- SAFE_MODE симулирует сделки, но проходит полный цикл состояния/логов.
- Округление qty/цены через ExchangeClient.*precision/round_* (если доступны).
- Частичный выход на TP1, перенос SL в безубыток, простой трейлинг.
- События через EventBus (если передан в конструкторе).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.trading.exchange_client import ExchangeClient, APIException
from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.utils.csv_handler import CSVHandler

logger = logging.getLogger(__name__)


@dataclass
class PositionSnapshot:
    active: bool
    symbol: Optional[str] = None
    entry_price: Optional[float] = None
    qty_base: Optional[float] = None
    qty_usd: Optional[float] = None
    sl_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None
    partial_taken: bool = False
    trailing_on: bool = False
    entry_time: Optional[str] = None
    buy_score: Optional[float] = None
    ai_score: Optional[float] = None


class PositionManager:
    """
    Минималистичный менеджер позиций под новый конвейер:
      - open(ctx)     — открытие по входному решению энтри-полиси
      - manage(price) — сопровождение (SL/TP/partial/trailing)
      - close_all(price, reason)
    """

    def __init__(
        self,
        exchange: ExchangeClient,
        state: StateManager,
        settings: Settings,
        events: Optional[EventBus] = None,
    ) -> None:
        self.exchange = exchange
        self.state = state
        self.settings = settings
        self.events = events
        self._lock = threading.RLock()
        logger.info("💼 PositionManager initialized")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _is_active(self) -> bool:
        st = getattr(self.state, "state", {}) or {}
        return bool(st.get("in_position") or st.get("opening"))

    def _emit(self, name: str, payload: Dict[str, Any]) -> None:
        try:
            if self.events is None:
                return
            if hasattr(self.events, "emit"):
                self.events.emit(name, payload)
            else:
                self.events.publish(name, payload)
        except Exception as e:
            logger.error(f"Event emit failed: {e}")

    def _round_amount(self, symbol: str, qty: float) -> float:
        try:
            if hasattr(self.exchange, "round_amount"):
                return float(self.exchange.round_amount(symbol, qty))
        except Exception:
            pass
        return float(qty)

    def _round_price(self, symbol: str, px: float) -> float:
        try:
            if hasattr(self.exchange, "round_price"):
                return float(self.exchange.round_price(symbol, px))
        except Exception:
            pass
        return float(px)

    def _market_min_cost(self, symbol: str) -> float:
        try:
            if hasattr(self.exchange, "market_min_cost"):
                v = self.exchange.market_min_cost(symbol)
                return float(v) if v else 5.0
        except Exception:
            pass
        return 5.0

    def _market_min_amount(self, symbol: str) -> float:
        try:
            if hasattr(self.exchange, "market_min_amount"):
                v = self.exchange.market_min_amount(symbol)
                return float(v) if v else 0.0
        except Exception:
            pass
        return 0.0

    # ── public API ───────────────────────────────────────────────────────────
    def open(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        ctx ожидает:
          symbol, side='buy', size_usd, entry_price, stop_loss, take_profit,
          buy_score, ai_score, confidence, details{...}
        """
        with self._lock:
            try:
                if self._is_active():
                    logger.warning("Position already active/opening — skip open()")
                    return None

                symbol = ctx.get("symbol") or getattr(self.settings, "SYMBOL", "BTC/USDT")
                if ctx.get("side", "buy").lower() != "buy":
                    logger.warning("Only LONG is supported in this version; reject non-buy")
                    return None

                entry_price = float(ctx.get("entry_price") or 0.0)
                if entry_price <= 0:
                    logger.error("No entry price provided")
                    return None

                size_usd = float(ctx.get("size_usd") or getattr(self.settings, "TRADE_AMOUNT", 100))
                size_usd = max(size_usd, self._market_min_cost(symbol))

                qty_base = size_usd / entry_price
                qty_base = self._round_amount(symbol, qty_base)

                # округление SL/TP под шаг цены (если задан)
                stop_loss = ctx.get("stop_loss")
                take_profit = ctx.get("take_profit")
                if stop_loss:  stop_loss  = self._round_price(symbol, float(stop_loss))
                if take_profit: take_profit = self._round_price(symbol, float(take_profit))

                # помечаем состояние "opening"
                self.state.set("opening", True)

                order_result: Optional[Dict[str, Any]] = None
                if bool(getattr(self.settings, "SAFE_MODE", True)):
                    # paper
                    order_result = {
                        "id": f"sim_{datetime.now().timestamp()}",
                        "symbol": symbol,
                        "amount": qty_base,
                        "price": entry_price,
                        "cost": qty_base * entry_price,
                        "side": "buy",
                        "type": "market",
                        "status": "closed",
                        "paper": True,
                    }
                    logger.info(f"📄 PAPER BUY {symbol} {qty_base:.8f} @ {entry_price:.6f} (${size_usd:.2f})")
                else:
                    # реальная торговля
                    if hasattr(self.exchange, "create_market_buy_order"):
                        order_result = self.exchange.create_market_buy_order(symbol, qty_base)
                    else:
                        raise APIException("ExchangeClient has no create_market_buy_order")
                    if not order_result:
                        raise APIException("Order execution failed")

                # обновляем state позицию
                pos = {
                    "in_position": True,
                    "opening": False,
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "qty_base": qty_base,
                    "qty_usd": qty_base * entry_price,
                    "sl_atr": float(stop_loss) if stop_loss else None,
                    "tp1_atr": float(take_profit) if take_profit else None,   # TP1 = заявленный TP
                    "tp2_atr": float(take_profit) if take_profit else None,   # можно держать одинаковым, если нет второй цели
                    "partial_taken": False,
                    "trailing_on": bool(getattr(self.settings, "TRAILING_STOP_ENABLE", False)),
                    "entry_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "buy_score": ctx.get("buy_score"),
                    "ai_score": ctx.get("ai_score"),
                    "confidence": ctx.get("confidence"),
                    "order_id": order_result.get("id") if order_result else None,
                    "last_manage_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                for k, v in pos.items():
                    self.state.set(k, v)

                # событие
                self._emit("position_opened", {**ctx, **pos})

                logger.info(f"✅ Position opened: {symbol} qty={qty_base:.8f} @ {entry_price:.6f}")
                return order_result

            except APIException as e:
                logger.error(f"Buy failed: {e}")
                self.state.set("opening", False)
                return None
            except Exception as e:
                logger.exception(f"Critical error in open(): {e}")
                self.state.set("opening", False)
                return None

    def manage(self, price: float, atr: float = 0.0) -> None:
        """Проверка SL/TP/частичного выхода + трейлинг (если включен)."""
        with self._lock:
            if not self._is_active():
                return
            try:
                symbol = self.state.get("symbol")
                entry_price = float(self.state.get("entry_price") or 0.0)
                qty_base = float(self.state.get("qty_base") or 0.0)
                sl = self.state.get("sl_atr")
                tp1 = self.state.get("tp1_atr")
                tp2 = self.state.get("tp2_atr")
                partial_taken = bool(self.state.get("partial_taken", False))

                if entry_price <= 0 or qty_base <= 0:
                    logger.error("Invalid position state (entry/qty)")
                    return

                # стоп
                if sl and price <= float(sl):
                    logger.info(f"🔴 Stop Loss hit: {price:.6f} <= {float(sl):.6f}")
                    self.close_all(price, "stop_loss")
                    return

                # TP1 — частичный
                if not partial_taken and tp1 and price >= float(tp1):
                    logger.info(f"🟢 Take Profit 1 hit: {price:.6f} >= {float(tp1):.6f}")
                    self._partial_close(price, fraction=0.5, reason="take_profit_1")
                    self.state.set("partial_taken", True)
                    # перенос SL к безубытку или чуть выше
                    if getattr(self.settings, "TRAILING_STOP_ENABLE", False):
                        new_sl = max(entry_price * 1.001, float(sl or 0))
                        self.state.set("sl_atr", new_sl)
                        logger.info(f"🔄 Move SL to breakeven: {new_sl:.6f}")

                # TP2 — полный выход
                if self.state.get("partial_taken", False) and tp2 and price >= float(tp2):
                    logger.info(f"🟢 Take Profit 2 hit: {price:.6f} >= {float(tp2):.6f}")
                    self.close_all(price, "take_profit_2")
                    return

                # Простой трейлинг (после частичного выхода)
                if getattr(self.settings, "TRAILING_STOP_ENABLE", False) and self.state.get("partial_taken", False):
                    self._update_trailing_stop(price, entry_price)

                # отметка manage
                self.state.set("last_manage_check", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

            except Exception as e:
                logger.exception(f"manage() failed: {e}")

    def close_all(self, price: float, reason: str) -> Optional[Dict[str, Any]]:
        """Полное закрытие позиции по рыночной цене."""
        with self._lock:
            if not self._is_active():
                logger.warning("No active position to close")
                return None
            try:
                symbol = self.state.get("symbol")
                entry_price = float(self.state.get("entry_price") or 0.0)
                qty_base = float(self.state.get("qty_base") or 0.0)
                qty_usd = float(self.state.get("qty_usd") or 0.0)
                buy_score = self.state.get("buy_score")
                ai_score = self.state.get("ai_score")
                entry_ts = self.state.get("entry_ts")

                if qty_base <= 0:
                    logger.error("Invalid qty_base in state")
                    return None

                order_result: Optional[Dict[str, Any]] = None
                if bool(getattr(self.settings, "SAFE_MODE", True)):
                    order_result = {
                        "id": f"sim_close_{datetime.now().timestamp()}",
                        "symbol": symbol,
                        "amount": qty_base,
                        "price": price,
                        "cost": qty_base * price,
                        "side": "sell",
                        "type": "market",
                        "status": "closed",
                        "paper": True,
                    }
                    logger.info(f"📄 PAPER SELL {symbol} {qty_base:.8f} @ {price:.6f}")
                else:
                    qty_to_sell = self._round_amount(symbol, qty_base)
                    min_amt = self._market_min_amount(symbol)
                    if qty_to_sell < min_amt:
                        logger.error(f"Qty {qty_to_sell} < min_amount {min_amt}")
                        return None
                    if hasattr(self.exchange, "create_market_sell_order"):
                        order_result = self.exchange.create_market_sell_order(symbol, qty_to_sell)
                    else:
                        raise APIException("ExchangeClient has no create_market_sell_order")
                    if not order_result:
                        raise APIException("Sell order execution failed")

                pnl_abs = (price - entry_price) * qty_base
                pnl_pct = (price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0

                # duration
                duration_minutes = 0.0
                if entry_ts:
                    try:
                        entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
                        duration_minutes = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60.0
                    except Exception:
                        pass

                # лог сделки
                try:
                    CSVHandler.log_close_trade({
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "symbol": symbol,
                        "side": "LONG",
                        "entry_price": entry_price,
                        "exit_price": price,
                        "qty_usd": qty_usd,
                        "pnl_pct": pnl_pct,
                        "pnl_abs": pnl_abs,
                        "reason": reason,
                        "buy_score": buy_score,
                        "ai_score": ai_score,
                        "duration_minutes": duration_minutes,
                        "close_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    })
                except Exception as e:
                    logger.error(f"Failed to log CSV close: {e}")

                # событие
                self._emit("position_closed", {
                    "symbol": symbol,
                    "exit_price": price,
                    "reason": reason,
                    "pnl_pct": pnl_pct,
                    "pnl_abs": pnl_abs,
                })

                # сброс state
                self.state.reset_position()
                self.state.start_cooldown()

                logger.info(f"✅ Position closed: {symbol} @ {price:.6f} | PnL {pnl_pct:.2f}% | {reason}")
                return order_result

            except Exception as e:
                logger.exception(f"close_all() failed: {e}")
                return None

    # ── internals ────────────────────────────────────────────────────────────
    def _partial_close(self, price: float, fraction: float, reason: str) -> None:
        symbol = self.state.get("symbol")
        qty_base = float(self.state.get("qty_base") or 0.0)
        if qty_base <= 0 or fraction <= 0:
            return
        qty_to_sell = qty_base * float(fraction)

        if bool(getattr(self.settings, "SAFE_MODE", True)):
            logger.info(f"📄 PAPER PARTIAL CLOSE {fraction*100:.0f}% @ {price:.6f}")
            remaining = qty_base - qty_to_sell
            self.state.set("qty_base", remaining)
            self.state.set("qty_usd", remaining * price)
            return

        try:
            qty_to_sell = self._round_amount(symbol, qty_to_sell)
            min_amt = self._market_min_amount(symbol)
            if qty_to_sell < min_amt:
                logger.warning(f"Skip partial: {qty_to_sell} < min_amount {min_amt}")
                return
            if hasattr(self.exchange, "create_market_sell_order"):
                self.exchange.create_market_sell_order(symbol, qty_to_sell)
            remaining = max(0.0, qty_base - qty_to_sell)
            self.state.set("qty_base", remaining)
            self.state.set("qty_usd", remaining * price)
            logger.info(f"📊 Partial close: {fraction*100:.0f}% @ {price:.6f} | {reason}")
        except Exception as e:
            logger.error(f"Partial close failed: {e}")

    def _update_trailing_stop(self, current_price: float, entry_price: float) -> None:
        cur_sl = float(self.state.get("sl_atr") or entry_price)
        trailing_pct = float(getattr(self.settings, "TRAILING_STOP_PCT", 0.5)) / 100.0
        new_sl = current_price * (1 - trailing_pct)
        if new_sl > cur_sl:
            self.state.set("sl_atr", new_sl)
            logger.info(f"🔄 Trailing SL: {cur_sl:.6f} → {new_sl:.6f}")

    # ── diagnostics ──────────────────────────────────────────────────────────
    def get_position_summary(self) -> Dict[str, Any]:
        if not self._is_active():
            return {"active": False}
        return {
            "active": True,
            "symbol": self.state.get("symbol"),
            "entry_price": self.state.get("entry_price"),
            "qty_usd": self.state.get("qty_usd"),
            "qty_base": self.state.get("qty_base"),
            "sl_price": self.state.get("sl_atr"),
            "tp1_price": self.state.get("tp1_atr"),
            "tp2_price": self.state.get("tp2_atr"),
            "partial_taken": self.state.get("partial_taken", False),
            "trailing_on": self.state.get("trailing_on", False),
            "entry_time": self.state.get("entry_ts"),
            "buy_score": self.state.get("buy_score"),
            "ai_score": self.state.get("ai_score"),
        }


__all__ = ["PositionManager", "PositionSnapshot"]
