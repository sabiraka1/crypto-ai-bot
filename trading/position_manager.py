import logging
from datetime import datetime, timedelta

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

        pnl_pct = 0.0
        if st.get('entry_price'):
            pnl_pct = (exit_price - st['entry_price']) / st['entry_price'] * 100.0

        st.update({
            'in_position': False,
            'last_exit_price': exit_price,
            'last_pnl_pct': pnl_pct,
            'last_close_reason': reason
        })
        self.state.save_state()
        logging.info(f"Closed LONG @ {exit_price:.4f} reason={reason} pnl={pnl_pct:.2f}%")
