import os
import logging
from datetime import datetime

# Безопасная работа с CSV
try:
    from utils.csv_handler import CSVHandler
except Exception:
    CSVHandler = None


class PositionManager:
    TP_PERCENT = 0.02   # 2% тейк-профит
    SL_PERCENT = -0.02  # -2% стоп-лосс
    TP1_ATR = 1.5
    TP2_ATR = 3.0
    SL_ATR = 1.0

    def __init__(self, exchange_client, state_manager, notify_entry_func=None, notify_close_func=None):
        self.ex = exchange_client
        self.state = state_manager
        # Функции уведомлений передаются извне
        self.notify_entry = notify_entry_func
        self.notify_close = notify_close_func

    # ========= ОТКРЫТИЕ LONG =========
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
            'side': 'long',
            'symbol': symbol,
            'entry_price': entry_price,
            'qty_usd': amount_usd,
            'tp_price_pct': entry_price * (1 + self.TP_PERCENT),
            'sl_price_pct': entry_price * (1 + self.SL_PERCENT),
            'tp1_atr': entry_price + self.TP1_ATR * atr,
            'tp2_atr': entry_price + self.TP2_ATR * atr,
            'sl_atr': entry_price - self.SL_ATR * atr,
            'open_time': datetime.utcnow().isoformat(),
            'buy_score': buy_score,
            'ai_score': ai_score,
            'trailing_on': False,
            'partial_taken': False
        })
        self.state.save_state()

        logging.info(f"✅ Открыт LONG {symbol} @ {entry_price:.4f} на сумму ${amount_usd:.2f}")

        # Отправка уведомления в Telegram
        try:
            if self.notify_entry:
                self.notify_entry(
                    symbol=symbol,
                    price=float(entry_price),
                    amount_usd=float(amount_usd),
                    tp=float(st['tp_price_pct']),
                    sl=float(st['sl_price_pct']),
                    tp1=float(st['tp1_atr']),
                    tp2=float(st['tp2_atr']),
                    buy_score=buy_score,
                    ai_score=ai_score,
                    amount_frac=amount_frac
                )
        except Exception as e:
            logging.error(f"notify_entry error: {e}")

        return order

    # ========= ЗАКРЫТИЕ ПОЗИЦИИ =========
    def close_all(self, symbol: str, exit_price: float, reason: str):
        st = self.state.state
        if not st.get('in_position'):
            logging.info("⏩ Пропуск: нет открытой позиции")
            return

        qty = st['qty_usd'] / exit_price if exit_price else 0
        try:
            self.ex.create_market_sell_order(symbol, qty)
        except Exception as e:
            logging.error(f"❌ Ошибка при закрытии позиции: {e}")

        entry = float(st.get('entry_price') or 0.0)
        pnl_pct = ((exit_price - entry) / entry * 100.0) if entry else 0.0
        qty_usd = float(st.get('qty_usd') or 0.0)
        pnl_abs = (exit_price - entry) * (qty_usd / entry) if entry else 0.0

        # Логирование сделки в CSV
        try:
            if CSVHandler:
                CSVHandler.append_closed_trade(symbol, entry, exit_price, pnl_pct, pnl_abs, reason)
        except Exception as e:
            logging.error(f"CSV log closed trade error: {e}")

        # Уведомление в Telegram
        try:
            if self.notify_close:
                self.notify_close(
                    symbol=symbol,
                    price=float(exit_price),
                    reason=reason,
                    pnl_pct=float(pnl_pct),
                    pnl_abs=float(pnl_abs),
                    buy_score=st.get('buy_score'),
                    ai_score=st.get('ai_score'),
                    amount_usd=qty_usd
                )
        except Exception as e:
            logging.error(f"notify_close error: {e}")

        st.update({
            'in_position': False,
            'close_price': exit_price,
            'last_reason': reason
        })
        self.state.save_state()

    # ========= УПРАВЛЕНИЕ ПОЗИЦИЕЙ (добавлен недостающий метод) =========
    def manage(self, symbol: str, current_price: float, atr: float):
        """Метод для управления открытой позицией (трейлинг, частичное закрытие)"""
        st = self.state.state
        if not st.get('in_position'):
            return

        entry_price = float(st.get('entry_price', 0))
        if entry_price <= 0:
            return

        # Простая логика: если цена выросла на 4%, закрываем
        pnl_pct = (current_price - entry_price) / entry_price * 100.0
        
        if pnl_pct >= 4.0:  # 4% прибыль
            self.close_all(symbol, current_price, "TP_4%")
        elif pnl_pct <= -3.0:  # -3% убыток
            self.close_all(symbol, current_price, "SL_3%")

    # ========= АЛЬТЕРНАТИВНОЕ ИМЯ МЕТОДА (для совместимости) =========
    def close_position(self, symbol: str, exit_price: float, reason: str):
        """Альтернативное имя для close_all (для совместимости)"""
        self.close_all(symbol, exit_price, reason)