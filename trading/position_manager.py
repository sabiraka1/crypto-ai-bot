import os
import logging
import threading
from datetime import datetime
from typing import Optional

from config.settings import TradingConfig

try:
    from utils.csv_handler import CSVHandler
except Exception:
    CSVHandler = None

CFG = TradingConfig()


class PositionManager:
    """Управление открытой позицией с защитой от двойного входа (RLock + флаг)."""

    TP_PERCENT = CFG.TAKE_PROFIT_PCT / 100
    SL_PERCENT = -CFG.STOP_LOSS_PCT / 100
    TP1_ATR = 1.5
    TP2_ATR = 3.0
    SL_ATR = 1.0

    def __init__(self, exchange_client, state_manager,
                 notify_entry_func=None, notify_close_func=None):
        self.ex = exchange_client
        self.state = state_manager
        self.notify_entry = notify_entry_func
        self.notify_close = notify_close_func

        # защита от гонок
        self._lock = threading.RLock()

    # --------------- helpers ---------------
    def _notify_entry_safe(self, *args, **kwargs):
        if not self.notify_entry:
            return
        try:
            self.notify_entry(*args, **kwargs)
        except Exception as e:
            logging.error(f"notify_entry error: {e}")

    def _notify_close_safe(self, *args, **kwargs):
        if not self.notify_close:
            return
        try:
            self.notify_close(*args, **kwargs)
        except Exception as e:
            logging.error(f"notify_close error: {e}")

    # --------------- long open / close ---------------
    def open_long(
        self,
        symbol: str,
        amount_usd: float,
        entry_price: float,
        atr: float,
        buy_score: Optional[float] = None,
        ai_score: Optional[float] = None,
        amount_frac: Optional[float] = None,
    ):
        """
        Открывает лонг с учётом блокировки и анти-реентри.
        """
        with self._lock:
            st = self.state.state

            # защита от двойного входа
            if st.get("opening"):
                logging.info("⏩ Пропуск: вход уже выполняется (opening=True)")
                return None

            if st.get("in_position"):
                logging.info("⏩ Пропуск: уже есть открытая позиция")
                return None

            st["opening"] = True
            self.state.save_state()

            try:
                # min_notional bump — чтобы стейт не расходился с биржей
                min_cost = self.ex.market_min_cost(symbol) or 0.0
                final_usd = max(float(amount_usd), float(min_cost))
                if final_usd > amount_usd:
                    logging.info(
                        f"🧩 amount bumped to min_notional: requested={amount_usd:.2f}, "
                        f"min={min_cost:.2f}, final={final_usd:.2f}"
                    )

                order = self.ex.create_market_buy_order(symbol, final_usd)
                if not order:
                    logging.error("❌ Buy order returned empty response")
                    return None

                # приблизительное количество базовой (для логики частичных выходов)
                qty_base = final_usd / entry_price if entry_price else 0.0

                st.update({
                    "in_position": True,
                    "opening": False,
                    "symbol": symbol,
                    "entry_price": float(entry_price),
                    "qty_usd": float(final_usd),
                    "qty_base": float(qty_base),
                    "buy_score": buy_score,
                    "ai_score": ai_score,
                    "amount_frac": amount_frac,
                    # статические цели в процентах
                    "tp_price_pct": entry_price * (1 + self.TP_PERCENT),
                    "sl_price_pct": entry_price * (1 + self.SL_PERCENT),
                    # цели по ATR
                    "tp1_atr": entry_price + self.TP1_ATR * atr,
                    "tp2_atr": entry_price + self.TP2_ATR * atr,
                    "sl_atr": entry_price - self.SL_ATR * atr,
                    # динамика
                    "trailing_on": False,
                    "partial_taken": False,
                })
                self.state.save_state()

                # уведомление
                self._notify_entry_safe(
                    symbol,
                    entry_price,
                    final_usd,
                    st["tp_price_pct"],
                    st["sl_price_pct"],
                    st["tp1_atr"],
                    st["tp2_atr"],
                    buy_score=buy_score,
                    ai_score=ai_score,
                    amount_frac=amount_frac,
                )
                return order

            except Exception as e:
                logging.error(f"❌ open_long failed: {e}")
                # при ошибке снимаем флаг opening
                st["opening"] = False
                self.state.save_state()
                return None

    def close_all(self, symbol: str, exit_price: float, reason: str):
        with self._lock:
            st = self.state.state
            if not st.get("in_position"):
                logging.info("Нет открытой позиции для закрытия")
                return None

            qty_usd = float(st.get("qty_usd", 0.0))
            qty_base = qty_usd / exit_price if exit_price else 0.0

            try:
                self.ex.create_market_sell_order(symbol, qty_base)
            except Exception as e:
                logging.error(f"❌ Sell order failed: {e}")

            entry_price = float(st.get("entry_price", 0.0))
            pnl_abs = (exit_price - entry_price) * qty_base
            pnl_pct = (exit_price - entry_price) / entry_price * 100.0 if entry_price else 0.0

            if CSVHandler:
                try:
                    CSVHandler.log_closed_trade(
                        datetime.utcnow(),
                        symbol,
                        entry_price,
                        exit_price,
                        qty_usd,
                        pnl_pct,
                        pnl_abs,
                        reason,
                    )
                except Exception as e:
                    logging.error(f"CSV log closed trade error: {e}")

            # уведомление о закрытии
            self._notify_close_safe(
                symbol=symbol,
                price=float(exit_price),
                reason=reason,
                pnl_pct=float(pnl_pct),
                pnl_abs=float(pnl_abs),
                buy_score=st.get("buy_score"),
                ai_score=st.get("ai_score"),
                amount_usd=qty_usd,
            )

            st.update({
                "in_position": False,
                "opening": False,
                "close_price": float(exit_price),
                "last_reason": reason,
            })
            self.state.save_state()
            return True

    # --------------- position manage ---------------
    def manage(self, symbol: str, last_price: float, atr: float):
        with self._lock:
            st = self.state.state
            if not st.get("in_position"):
                return

            entry = float(st.get("entry_price") or 0.0)
            tp_pct = float(st.get("tp_price_pct") or 0.0)
            sl_pct = float(st.get("sl_price_pct") or 0.0)
            tp1_atr = float(st.get("tp1_atr") or 0.0)
            tp2_atr = float(st.get("tp2_atr") or 0.0)
            sl_atr = float(st.get("sl_atr") or 0.0)
            trailing_on = bool(st.get("trailing_on"))
            partial_taken = bool(st.get("partial_taken"))

            if entry <= 0:
                return

            # SL (pct или ATR)
            if (sl_pct and last_price <= sl_pct) or (sl_atr and last_price <= sl_atr):
                self.close_all(symbol, last_price, "SL_hit")
                return

            # TP (pct или ATR2)
            if (tp_pct and last_price >= tp_pct) or (tp2_atr and last_price >= tp2_atr):
                self.close_all(symbol, last_price, "TP_hit")
                return

            # Partial at TP1 (ATR1)
            if (not partial_taken) and tp1_atr and last_price >= tp1_atr:
                qty_total = float(st.get("qty_usd", 0.0)) / last_price
                qty_sell = qty_total / 2.0
                try:
                    self.ex.create_market_sell_order(symbol, qty_sell)
                except Exception as e:
                    logging.error(f"❌ Partial close failed: {e}")
                else:
                    st["qty_usd"] = float(st.get("qty_usd", 0.0)) / 2.0
                    st["partial_taken"] = True
                    st["trailing_on"] = True
                    # подтягиваем стоп-лосс
                    st["sl_atr"] = max(entry, last_price - self.SL_ATR * atr)
                    st["sl_price_pct"] = max(entry, last_price * (1 + self.SL_PERCENT))
                    self.state.save_state()
                return

            # Трейлинг-стоп по ATR
            if trailing_on:
                new_sl_atr = last_price - self.SL_ATR * atr
                if new_sl_atr > sl_atr:
                    st["sl_atr"] = new_sl_atr
                    st["sl_price_pct"] = max(st["sl_price_pct"], last_price * (1 + self.SL_PERCENT))
                    self.state.save_state()

    # совместимость со старым вызовом
    def close_position(self, symbol: str, exit_price: float, reason: str):
        return self.close_all(symbol, exit_price, reason)
