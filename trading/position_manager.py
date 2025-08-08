import os
import logging
from datetime import datetime

from config.settings import TradingConfig

try:
    from utils.csv_handler import CSVHandler
except Exception:
    CSVHandler = None

CFG = TradingConfig()

class PositionManager:
    """Управление открытой позицией"""

    TP_PERCENT = CFG.TAKE_PROFIT_PCT / 100
    SL_PERCENT = -CFG.STOP_LOSS_PCT / 100
    TP1_ATR = 1.5
    TP2_ATR = 3.0
    SL_ATR = 1.0

    def __init__(self, exchange_client, state_manager, notify_entry_func=None, notify_close_func=None):
        self.ex = exchange_client
        self.state = state_manager
        self.notify_entry = notify_entry_func
        self.notify_close = notify_close_func

    def open_long(self, symbol: str, amount_usd: float, entry_price: float, atr: float,
                  buy_score: float = None, ai_score: float = None, amount_frac: float = None):
        st = self.state.state
        if st.get('in_position'):
            logging.info("⏩ Пропуск: уже есть открытая позиция")
            return None

        order = self.ex.create_market_buy_order(symbol, amount_usd)
        if not order:
            return None

        st.update({
            'in_position': True,
            'symbol': symbol,
            'entry_price': entry_price,
            'qty_usd': amount_usd,
            'buy_score': buy_score,
            'ai_score': ai_score,
            'amount_frac': amount_frac,
            'tp_price_pct': entry_price * (1 + self.TP_PERCENT),
            'sl_price_pct': entry_price * (1 + self.SL_PERCENT),
            'tp1_atr': entry_price + self.TP1_ATR * atr,
            'tp2_atr': entry_price + self.TP2_ATR * atr,
            'sl_atr': entry_price - self.SL_ATR * atr,
            'trailing_on': False,
            'partial_taken': False
        })
        self.state.save_state()

        try:
            if self.notify_entry:
                self.notify_entry(symbol, entry_price, amount_usd,
                                  st['tp_price_pct'], st['sl_price_pct'],
                                  st['tp1_atr'], st['tp2_atr'],
                                  buy_score=buy_score, ai_score=ai_score, amount_frac=amount_frac)
        except Exception as e:
            logging.error(f"notify_entry error: {e}")

    def close_all(self, symbol: str, exit_price: float, reason: str):
        st = self.state.state
        if not st.get('in_position'):
            logging.info("Нет открытой позиции для закрытия")
            return None

        qty_usd = float(st.get('qty_usd', 0.0))
        qty_base = qty_usd / exit_price if exit_price else 0.0
        try:
            self.ex.create_market_sell_order(symbol, qty_base)
        except Exception as e:
            logging.error(f"❌ Sell order failed: {e}")

        entry_price = float(st.get('entry_price', 0.0))
        pnl_abs = (exit_price - entry_price) * qty_base
        pnl_pct = (exit_price - entry_price) / entry_price * 100.0 if entry_price else 0.0

        if CSVHandler:
            try:
                CSVHandler.log_closed_trade(datetime.utcnow(), symbol, entry_price, exit_price,
                                            qty_usd, pnl_pct, pnl_abs, reason)
            except Exception as e:
                logging.error(f"CSV log closed trade error: {e}")

        try:
            if self.notify_close:
                self.notify_close(symbol=symbol, price=float(exit_price), reason=reason,
                                  pnl_pct=float(pnl_pct), pnl_abs=float(pnl_abs),
                                  buy_score=st.get('buy_score'), ai_score=st.get('ai_score'),
                                  amount_usd=qty_usd)
        except Exception as e:
            logging.error(f"notify_close error: {e}")

        st.update({'in_position': False, 'close_price': exit_price, 'last_reason': reason})
        self.state.save_state()

    def manage(self, symbol: str, last_price: float, atr: float):
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
            qty_total = float(st.get("qty_usd", 0.0)) / last_price
            qty_sell = qty_total / 2
            try:
                self.ex.create_market_sell_order(symbol, qty_sell)
            except Exception as e:
                logging.error(f"❌ Partial close failed: {e}")
            else:
                st["qty_usd"] = float(st.get("qty_usd", 0.0)) / 2
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
                st["sl_price_pct"] = max(st["sl_price_pct"], last_price * (1 + self.SL_PERCENT))
                self.state.save_state()

    def close_position(self, symbol: str, exit_price: float, reason: str):
        self.close_all(symbol, exit_price, reason)
