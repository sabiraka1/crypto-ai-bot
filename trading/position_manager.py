import os
import logging
from datetime import datetime, timedelta

# уведомления в TG
try:
    from telegram.bot_handler import notify_entry, notify_close
except Exception:
    notify_entry = None
    notify_close = None

# безопасная работа с CSV
try:
    from utils.csv_handler import CSVHandler
except Exception:
    CSVHandler = None


class PositionManager:
    """
    Управление позицией: открытие/ведение/закрытие.
    Смешанный RM: процентный TP/SL (предохранитель) + ATR-лестница (TP1/TP2) + трейлинг после TP1.
    Только LONG на споте.
    """
    def __init__(self, exchange_client, state_manager):
        self.ex = exchange_client
        self.state = state_manager

        # Процентные предохранители
        self.TP_PERCENT = 0.02     # +2%
        self.SL_PERCENT = -0.02    # -2%

        # ATR-ступени
        self.TP1_ATR = 1.5
        self.TP2_ATR = 2.0
        self.SL_ATR  = 1.5

        # Трейлинг после TP1
        self.TRAILING_TRIGGER_ATR = 1.0
        self.TRAILING_STEP_ATR    = 0.5

        # Лимит времени
        self.TIMEOUT_HOURS = 2

    # ========= ТВОИ МЕТОДЫ (с уведомлениями) =========
    def open_long(self, symbol: str, amount_usd: float, entry_price: float, atr: float):
        st = self.state.state
        if st.get('in_position'):
            logging.info("Skip open_long: already in position")
            return None

        order = self.ex.create_market_buy_order(symbol, amount_usd)
        if not order:
            return None

        st.update({
            'in_position': True,
            'side': 'long',
            'symbol': symbol,
            'entry_price': entry_price,
            'qty_usd': amount_usd,
            # процентные предохранители
            'tp_price_pct': entry_price * (1 + self.TP_PERCENT),
            'sl_price_pct': entry_price * (1 + self.SL_PERCENT),
            # ATR-уровни
            'tp1_atr': entry_price + self.TP1_ATR * atr,
            'tp2_atr': entry_price + self.TP2_ATR * atr,
            'sl_atr': entry_price - self.SL_ATR * atr,
            # трейлинг
            'trailing_on': False,
            'partial_taken': False,
            'open_time': datetime.utcnow().isoformat()
        })
        self.state.save_state()

        logging.info(f"Opened LONG {symbol} @ {entry_price:.4f}")

        # 🔔 TG уведомление о входе
        try:
            if notify_entry:
                notify_entry(
                    symbol=symbol,
                    price=float(entry_price),
                    amount_usd=float(amount_usd),
                    tp=float(st['tp_price_pct']),
                    sl=float(st['sl_price_pct']),
                    tp1=float(st['tp1_atr']),
                    tp2=float(st['tp2_atr'])
                )
        except Exception as e:
            logging.error(f"notify_entry error: {e}")

        return order

    def manage(self, symbol: str, last_price: float, atr: float):
        st = self.state.state
        if not st.get('in_position'):
            return

        # 1) timeout
        opened = datetime.fromisoformat(st['open_time'])
        if datetime.utcnow() - opened >= timedelta(hours=self.TIMEOUT_HOURS):
            self.close_all(symbol, last_price, reason='timeout')
            return

        # 2) процентные предохранители
        if last_price >= st['tp_price_pct']:
            self.close_all(symbol, last_price, reason='tp_pct'); return
        if last_price <= st['sl_price_pct']:
            self.close_all(symbol, last_price, reason='sl_pct'); return

        # 3) ATR-логика
        # TP1 — частичный выход: для спота просто включаем трейлинг и переносим SL в б/у
        if not st.get('partial_taken') and last_price >= st['tp1_atr']:
            st['partial_taken'] = True
            st['sl_atr'] = max(st['sl_atr'], st['entry_price'] * 1.001)  # чутка выше б/у
            st['trailing_on'] = True
            self.state.save_state()
            logging.info("Partial take at TP1; SL->breakeven; trailing ON")

        # Трейлинг после TP1
        if st.get('trailing_on') and atr and last_price >= st['entry_price'] + self.TRAILING_TRIGGER_ATR * atr:
            new_sl = max(st['sl_atr'], last_price - self.TRAILING_STEP_ATR * atr)
            if new_sl > st['sl_atr']:
                st['sl_atr'] = new_sl
                self.state.save_state()
                logging.info(f"Trailing SL moved to {new_sl:.4f}")

        # TP2 — полное закрытие
        if last_price >= st['tp2_atr']:
            self.close_all(symbol, last_price, reason='tp2_atr'); return

        # стоп по ATR
        if last_price <= st['sl_atr']:
            self.close_all(symbol, last_price, reason='sl_atr'); return

    def close_all(self, symbol: str, exit_price: float, reason: str):
        st = self.state.state
        if not st.get('in_position'):
            return

        # рыночное закрытие лонга: продаём на сумму в USD, пересчитав в количество
        qty = st['qty_usd'] / exit_price if exit_price else 0
        try:
            self.ex.create_market_sell_order(symbol, qty)
        except Exception as e:
            logging.error(f"close_all sell error: {e}")

        # PnL
        entry = float(st.get('entry_price') or 0.0)
        pnl_pct = ((exit_price - entry) / entry * 100.0) if entry else 0.0
        # эквивалент по USD: qty_usd / entry = фактическое количество
        qty_usd = float(st.get('qty_usd') or 0.0)
        pnl_abs = (exit_price - entry) * (qty_usd / entry) if entry else 0.0

        # лог в CSV (если есть утилита)
        try:
            if CSVHandler:
                CSVHandler.append_to_csv({
                    "time": datetime.utcnow().isoformat(),
                    "symbol": symbol,
                    "side": "LONG",
                    "entry_price": entry,
                    "close_price": float(exit_price),
                    "qty_usd": qty_usd,
                    "pnl_abs": float(pnl_abs),
                    "pnl_pct": float(pnl_pct),
                    "reason": reason
                }, "closed_trades.csv")
        except Exception as e:
            logging.error(f"write closed_trades.csv failed: {e}")

        # обновляем состояние
        st.update({
            'in_position': False,
            'last_exit_price': exit_price,
            'last_pnl_pct': pnl_pct,
            'last_close_reason': reason
        })
        self.state.save_state()

        logging.info(f"Closed LONG @ {exit_price:.4f} reason={reason} pnl={pnl_pct:.2f}%")

        # 🔔 TG уведомление о выходе
        try:
            if notify_close:
                notify_close(
                    symbol=symbol,
                    price=float(exit_price),
                    reason=reason,
                    pnl_pct=float(pnl_pct),
                    pnl_abs=float(pnl_abs)
                )
        except Exception as e:
            logging.error(f"notify_close error: {e}")

    # ========= Совместимость с основным циклом =========
    def open_position(self, exchange_client, symbol: str, usd_amount: float = None):
        """
        Совместимость с вызовом из основного цикла:
        - если usd_amount не передан (старый main), берём из .env TRADE_AMOUNT или 50
        - берём текущую цену через exchange_client/self.ex
        - ATR для старта 0.0 (процентные предохранители всё равно работают)
        """
        if usd_amount is None:
            try:
                usd_amount = float(os.getenv("TRADE_AMOUNT", "50"))
            except Exception:
                usd_amount = 50.0

        try:
            price = (exchange_client or self.ex).get_last_price(symbol)
        except Exception:
            price = self.ex.get_last_price(symbol)

        atr = 0.0
        return self.open_long(symbol, usd_amount, price, atr)

    def close_position(self, exchange_client, reason: str = "signal"):
        """
        Совместимость: закрыть всю позицию по текущей цене и причине.
        """
        st = self.state.state
        if not st.get('in_position'):
            return {"status": "noop", "detail": "no position"}

        symbol = st.get('symbol')
        try:
            last = (exchange_client or self.ex).get_last_price(symbol)
        except Exception:
            last = self.ex.get_last_price(symbol)

        self.close_all(symbol, last, reason)
        return {"status": "closed", "symbol": symbol, "close_price": last, "reason": reason}
