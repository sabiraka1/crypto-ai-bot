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
    SL_PERCENT = -float(getattr(CFG, "STOP_LOSS_PCT", getattr(CFG, "STOP_LOSS_PCT", 2.0))) / 100
    TP1_ATR = 1.5
    TP2_ATR = 3.0
    SL_ATR = 1.0

    def __init__(self, exchange_client, state_manager,
                 notify_entry_func=None, notify_close_func=None):
        self.ex = exchange_client
        self.state = state_manager
        self.notify_entry = notify_entry_func
        self.notify_close = notify_close_func
        self._lock = threading.RLock()

    # ---------- helpers ----------
    def _notify_entry_safe(self, *args, **kwargs):
        if self.notify_entry:
            try:
                self.notify_entry(*args, **kwargs)
            except Exception as e:
                logging.error(f"notify_entry error: {e}")

    def _notify_close_safe(self, *args, **kwargs):
        if self.notify_close:
            try:
                self.notify_close(*args, **kwargs)
            except Exception as e:
                logging.error(f"notify_close error: {e}")

    # ---------- long open ----------
    def open_long(
        self,
        symbol: str,
        amount_usd: float,
        entry_price: float,
        atr: float,
        buy_score: Optional[float] = None,
        ai_score: Optional[float] = None,
        amount_frac: Optional[float] = None,
        final_score: Optional[float] = None,
        market_condition: Optional[str] = None,
        pattern: Optional[str] = None,
    ):
        """Открывает лонг и сохраняет расширенные данные в state для CSV."""
        with self._lock:
            st = self.state.state
            if st.get("opening") or st.get("in_position"):
                logging.info("⏩ Пропуск: уже есть процесс входа или открытая позиция")
                return None

            st["opening"] = True
            self.state.save_state()

            try:
                # Проверка на минимальный размер сделки
                min_cost = self.ex.market_min_cost(symbol) or 0.0
                final_usd = max(float(amount_usd), float(min_cost))
                if final_usd > amount_usd:
                    logging.info(f"🧩 amount bumped to min_notional: requested={amount_usd:.2f}, min={min_cost:.2f}")

                order = self.ex.create_market_buy_order(symbol, final_usd)
                if not order:
                    logging.error("❌ Buy order returned empty response")
                    return None

                qty_base = final_usd / entry_price if entry_price else 0.0
                entry_ts = datetime.utcnow().isoformat() + "Z"

                # Доп. данные при входе
                try:
                    rsi_entry = self.ex.get_rsi(symbol)
                except Exception:
                    rsi_entry = ""

                atr_entry = atr
                pattern_entry = pattern or ""

                st.update({
                    "in_position": True,
                    "opening": False,
                    "symbol": symbol,
                    "entry_price": float(entry_price),
                    "qty_usd": float(final_usd),
                    "qty_base": float(qty_base),
                    "buy_score": buy_score,
                    "ai_score": ai_score,
                    "final_score": final_score,
                    "amount_frac": amount_frac,
                    "entry_ts": entry_ts,
                    "market_condition": market_condition or "",
                    "pattern": pattern_entry,
                    "rsi_entry": rsi_entry,
                    "atr_entry": atr_entry,
                    # статические цели
                    "tp_price_pct": entry_price * (1 + self.TP_PERCENT),
                    "sl_price_pct": entry_price * (1 + self.SL_PERCENT),
                    # ATR цели
                    "tp1_atr": entry_price + self.TP1_ATR * atr,
                    "tp2_atr": entry_price + self.TP2_ATR * atr,
                    "sl_atr": entry_price - self.SL_ATR * atr,
                    # динамика
                    "trailing_on": False,
                    "partial_taken": False,
                })
                self.state.save_state()

                self._notify_entry_safe(
                    symbol, entry_price, final_usd,
                    st["tp_price_pct"], st["sl_price_pct"],
                    st["tp1_atr"], st["tp2_atr"],
                    buy_score=buy_score, ai_score=ai_score, amount_frac=amount_frac
                )
                return order

            except Exception as e:
                logging.error(f"❌ open_long failed: {e}")
                st["opening"] = False
                self.state.save_state()
                return None

    # ---------- close ----------
    def close_all(self, symbol: str, exit_price: float, reason: str):
        with self._lock:
            st = self.state.state
            if not st.get("in_position"):
                logging.info("Нет открытой позиции для закрытия")
                return None

            qty_usd = float(st.get("qty_usd", 0.0))
            qty_base = qty_usd / exit_price if exit_price else 0.0

            # Проверка на минимальный размер при закрытии
            min_amount = self.ex.market_min_amount(symbol) or 0.0
            if qty_base < min_amount:
                logging.error(f"❌ Sell order too small: {qty_base:.8f} < min {min_amount}")
                return None

            try:
                self.ex.create_market_sell_order(symbol, qty_base)
            except Exception as e:
                logging.error(f"❌ Sell order failed: {e}")

            entry_price = float(st.get("entry_price", 0.0))
            pnl_abs = (exit_price - entry_price) * qty_base
            pnl_pct = (exit_price - entry_price) / entry_price * 100.0 if entry_price else 0.0

            exit_ts = datetime.utcnow().isoformat() + "Z"
            entry_ts = st.get("entry_ts", exit_ts)
            try:
                duration_min = round((datetime.fromisoformat(exit_ts.replace("Z", "")) -
                                      datetime.fromisoformat(entry_ts.replace("Z", ""))).total_seconds() / 60, 2)
            except Exception:
                duration_min = ""

            # RSI на выходе
            try:
                rsi_exit = self.ex.get_rsi(symbol)
            except Exception:
                rsi_exit = ""

            rsi_entry = st.get("rsi_entry", "")
            atr_entry = st.get("atr_entry", "")
            pattern_entry = st.get("pattern", "")

            # MFE / MAE с исправленным parse8601
            mfe_pct, mae_pct = "", ""
            try:
                ohlcv = self.ex.fetch_ohlcv(symbol, timeframe="15m", since=self.ex.exchange.parse8601(entry_ts))
                prices = [c[4] for c in ohlcv]
                if prices:
                    max_price = max(prices)
                    min_price = min(prices)
                    mfe_pct = (max_price - entry_price) / entry_price * 100.0
                    mae_pct = (min_price - entry_price) / entry_price * 100.0
            except Exception as e:
                logging.error(f"MFE/MAE calc error: {e}")

            # Запись в closed_trades.csv
            if CSVHandler:
                try:
                    CSVHandler.log_closed_trade({
                        "timestamp": exit_ts,
                        "symbol": symbol,
                        "side": "EXIT",
                        "entry_price": entry_price,
                        "exit_price": float(exit_price),
                        "qty_usd": qty_usd,
                        "pnl_pct": pnl_pct,
                        "pnl_abs": pnl_abs,
                        "reason": reason,
                        "buy_score": st.get("buy_score", ""),
                        "ai_score": st.get("ai_score", ""),
                        "final_score": st.get("final_score", ""),
                        "entry_ts": entry_ts,
                        "exit_ts": exit_ts,
                        "duration_min": duration_min,
                        "market_condition": st.get("market_condition", ""),
                        "pattern": pattern_entry,
                        "rsi_entry": rsi_entry,
                        "rsi_exit": rsi_exit,
                        "atr_entry": atr_entry,
                        "mfe_pct": mfe_pct,
                        "mae_pct": mae_pct
                    })
                except Exception as e:
                    logging.error(f"CSV log closed trade error: {e}")

            self._notify_close_safe(
                symbol=symbol, price=float(exit_price), reason=reason,
                pnl_pct=float(pnl_pct), pnl_abs=float(pnl_abs),
                buy_score=st.get("buy_score"), ai_score=st.get("ai_score"), amount_usd=qty_usd
            )

            st.update({
                "in_position": False,
                "opening": False,
                "close_price": float(exit_price),
                "last_reason": reason,
            })
            self.state.save_state()
            return True

    # ---------- manage ----------
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

            if (sl_pct and last_price <= sl_pct) or (sl_atr and last_price <= sl_atr):
                self.close_all(symbol, last_price, "SL_hit")
                return

            if (tp_pct and last_price >= tp_pct) or (tp2_atr and last_price >= tp2_atr):
                self.close_all(symbol, last_price, "TP_hit")
                return

            if (not partial_taken) and tp1_atr and last_price >= tp1_atr:
                qty_total = float(st.get("qty_usd", 0.0)) / last_price if last_price else 0.0
                qty_sell = qty_total / 2.0

                min_amount = self.ex.market_min_amount(symbol) or 0.0
                if qty_sell < min_amount:
                    logging.error(f"❌ Partial close too small: {qty_sell:.8f} < min {min_amount}")
                    return

                try:
                    self.ex.create_market_sell_order(symbol, qty_sell)
                except Exception as e:
                    logging.error(f"❌ Partial close failed: {e}")
                else:
                    st["qty_usd"] /= 2.0
                    st["partial_taken"] = True
                    st["trailing_on"] = True
                    st["sl_atr"] = max(entry, last_price - self.SL_ATR * atr)
                    st["sl_price_pct"] = max(entry, last_price * (1 + self.SL_PERCENT))
                    self.state.save_state()
                return

            if trailing_on:
                new_sl_atr = last_price - self.SL_ATR * atr
                if new_sl_atr > sl_atr:
                    st["sl_atr"] = new_sl_atr
                    st["sl_price_pct"] = max(st.get("sl_price_pct", entry),
                                             last_price * (1 + self.SL_PERCENT))
                    self.state.save_state()

    def close_position(self, symbol: str, exit_price: float, reason: str):
        return self.close_all(symbol, exit_price, reason)
