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
    """
    Управление открытой позицией с защитой от двойного входа (RLock + флаг).
    ✅ ИСПРАВЛЕНИЯ:
    - Строгая защита от множественных позиций
    - Корректное отслеживание стопов и тейк-профитов
    - Улучшенное управление рисками
    """

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
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Открывает лонг с ЖЕСТКОЙ защитой от дублей
        """
        with self._lock:
            st = self.state.state
            
            # ✅ СТРОГАЯ ПРОВЕРКА: НЕ ПОЗВОЛЯЕМ множественные позиции
            if st.get("opening") or st.get("in_position"):
                logging.warning(f"⚠️ ДУБЛИКАТ ВХОДА ЗАБЛОКИРОВАН! opening={st.get('opening')}, in_position={st.get('in_position')}")
                return None

            # ✅ АТОМАРНО устанавливаем флаг блокировки
            st["opening"] = True
            st["in_position"] = False  # На всякий случай сбрасываем
            self.state.save_state()
            
            logging.info(f"🔒 Вход заблокирован для других процессов. Начинаем открытие позиции...")

            try:
                # Проверка на минимальный размер сделки
                min_cost = self.ex.market_min_cost(symbol) or 0.0
                final_usd = max(float(amount_usd), float(min_cost))
                if final_usd > amount_usd:
                    logging.info(f"🧩 amount bumped to min_notional: requested={amount_usd:.2f}, min={min_cost:.2f}")

                # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА перед ордером
                current_st = self.state.state
                if current_st.get("in_position"):
                    logging.error("❌ Состояние изменилось во время выполнения! Отменяем ордер.")
                    st["opening"] = False
                    self.state.save_state()
                    return None

                # Выполняем ордер
                order = self.ex.create_market_buy_order(symbol, final_usd)
                if not order:
                    logging.error("❌ Buy order returned empty response")
                    st["opening"] = False
                    self.state.save_state()
                    return None

                # Получаем фактическое количество из ордера или рассчитываем
                if order.get("filled") is not None:
                    qty_base = float(order["filled"])
                elif order.get("amount") is not None:
                    qty_base = float(order["amount"])
                else:
                    qty_base = final_usd / entry_price if entry_price else 0.0

                # Фактическая цена из ордера или переданная
                actual_entry_price = float(order.get("avg", entry_price))
                
                entry_ts = datetime.utcnow().isoformat() + "Z"

                # Доп. данные при входе
                try:
                    rsi_entry = self.ex.get_rsi(symbol) if hasattr(self.ex, 'get_rsi') else ""
                except Exception:
                    rsi_entry = ""

                atr_entry = atr
                pattern_entry = pattern or ""

                # ✅ АТОМАРНО обновляем состояние позиции
                st.update({
                    "in_position": True,
                    "opening": False,  # Снимаем блокировку
                    "symbol": symbol,
                    "entry_price": float(actual_entry_price),
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
                    # ✅ ИСПРАВЛЕННЫЕ статические цели
                    "tp_price_pct": float(actual_entry_price * (1 + self.TP_PERCENT)),
                    "sl_price_pct": float(actual_entry_price * (1 + self.SL_PERCENT)),
                    # ✅ ИСПРАВЛЕННЫЕ ATR цели  
                    "tp1_atr": float(actual_entry_price + self.TP1_ATR * atr),
                    "tp2_atr": float(actual_entry_price + self.TP2_ATR * atr),
                    "sl_atr": float(actual_entry_price - self.SL_ATR * atr),
                    # динамика
                    "trailing_on": False,
                    "partial_taken": False,
                    # дополнительные поля для отслеживания
                    "position_opened_at": datetime.utcnow().isoformat(),
                    "last_manage_check": None,
                })
                self.state.save_state()
                
                logging.info(f"✅ Позиция успешно открыта: {symbol} @ {actual_entry_price:.4f}, размер ${final_usd:.2f}")

                self._notify_entry_safe(
                    symbol, actual_entry_price, final_usd,
                    st["tp_price_pct"], st["sl_price_pct"],
                    st["tp1_atr"], st["tp2_atr"],
                    buy_score=buy_score, ai_score=ai_score, amount_frac=amount_frac
                )
                return order

            except Exception as e:
                logging.error(f"❌ open_long failed: {e}")
                # ✅ В случае ошибки обязательно снимаем блокировки
                st["opening"] = False
                st["in_position"] = False
                self.state.save_state()
                return None

    # ---------- close ----------
    def close_all(self, symbol: str, exit_price: float, reason: str):
        """
        ✅ ИСПРАВЛЕНИЕ: Закрывает ВСЮ позицию по текущей рыночной цене
        """
        with self._lock:
            st = self.state.state
            if not st.get("in_position"):
                logging.info("ℹ️ Нет открытой позиции для закрытия")
                return None

            logging.info(f"🔄 Начинаем закрытие позиции {symbol}, причина: {reason}")

            try:
                # Получаем актуальную цену если не передана
                if not exit_price or exit_price <= 0:
                    exit_price = self.ex.get_last_price(symbol)
                    if not exit_price or exit_price <= 0:
                        logging.error("❌ Cannot get current price for closing")
                        return None

                entry_price = float(st.get("entry_price", 0.0))
                qty_usd = float(st.get("qty_usd", 0.0))
                qty_base_stored = float(st.get("qty_base", 0.0))
                
                # ✅ ИСПРАВЛЕНИЕ: Используем сохраненное количество базовой валюты
                # Это количество мы ТОЧНО купили при входе
                qty_base = qty_base_stored
                if qty_base <= 0:
                    logging.error("❌ Cannot determine amount to sell")
                    return None

                # ✅ Округляем согласно точности биржи
                qty_base = self.ex.round_amount(symbol, qty_base)
                
                # ✅ Проверяем минимальное количество
                min_amount = self.ex.market_min_amount(symbol) or 0.0
                if qty_base < min_amount:
                    if self.ex.safe_mode:
                        # В SAFE_MODE продаем все что можем
                        logging.warning(f"⚠️ SAFE_MODE: selling {qty_base:.8f} < min {min_amount:.8f}")
                    else:
                        # В реальном режиме пытаемся продать весь доступный баланс
                        try:
                            free_base = self.ex.get_free_base(symbol)
                            if free_base >= min_amount:
                                qty_base = self.ex.round_amount(symbol, free_base)
                                logging.info(f"🔄 Adjusting to available balance: {qty_base:.8f}")
                            else:
                                logging.error(f"❌ Insufficient balance to sell: have {free_base:.8f}, need {min_amount:.8f}")
                                # Принудительно закрываем позицию в state даже если не можем продать
                                self._force_close_position(symbol, exit_price, f"{reason}_insufficient_balance")
                                return None
                        except Exception as e:
                            logging.error(f"❌ Error checking balance: {e}")
                            self._force_close_position(symbol, exit_price, f"{reason}_balance_error")
                            return None

                # Выполняем продажу
                try:
                    sell_order = self.ex.create_market_sell_order(symbol, qty_base)
                    actual_qty_sold = float(sell_order.get("filled", qty_base))
                    actual_exit_price = float(sell_order.get("avg", exit_price))
                    logging.info(f"✅ Sell order executed: {actual_qty_sold:.8f} @ {actual_exit_price:.4f}")
                except Exception as e:
                    logging.error(f"❌ Sell order failed: {e}")
                    # В случае ошибки продажи, пытаемся продать все доступное
                    try:
                        logging.info("🔄 Attempting to sell all available base balance")
                        sell_order = self.ex.sell_all_base(symbol)
                        actual_qty_sold = float(sell_order.get("filled", qty_base))
                        actual_exit_price = float(sell_order.get("avg", exit_price))
                    except Exception as e2:
                        logging.error(f"❌ sell_all_base also failed: {e2}")
                        # В критической ситуации помечаем позицию как закрытую
                        if self.ex.safe_mode:
                            actual_qty_sold = qty_base
                            actual_exit_price = exit_price
                            logging.warning("⚠️ SAFE_MODE: Force closing position with paper values")
                        else:
                            self._force_close_position(symbol, exit_price, f"{reason}_sell_failed")
                            return None

                # Рассчитываем PnL на основе фактических данных
                pnl_abs = (actual_exit_price - entry_price) * actual_qty_sold if entry_price > 0 else 0.0
                pnl_pct = (actual_exit_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0

                exit_ts = datetime.utcnow().isoformat() + "Z"
                entry_ts = st.get("entry_ts", exit_ts)
                
                # Рассчитываем длительность
                try:
                    duration_min = round((datetime.fromisoformat(exit_ts.replace("Z", "")) -
                                          datetime.fromisoformat(entry_ts.replace("Z", ""))).total_seconds() / 60, 2)
                except Exception:
                    duration_min = ""

                # RSI на выходе
                try:
                    rsi_exit = self.ex.get_rsi(symbol) if hasattr(self.ex, 'get_rsi') else ""
                except Exception:
                    rsi_exit = ""

                rsi_entry = st.get("rsi_entry", "")
                atr_entry = st.get("atr_entry", "")
                pattern_entry = st.get("pattern", "")

                # MFE / MAE расчет
                mfe_pct, mae_pct = "", ""
                try:
                    if hasattr(self.ex.exchange, 'parse8601'):
                        ohlcv = self.ex.fetch_ohlcv(symbol, timeframe="15m", since=self.ex.exchange.parse8601(entry_ts))
                        prices = [c[4] for c in ohlcv]
                        if prices:
                            max_price = max(prices)
                            min_price = min(prices)
                            mfe_pct = (max_price - entry_price) / entry_price * 100.0
                            mae_pct = (min_price - entry_price) / entry_price * 100.0
                except Exception as e:
                    logging.debug(f"MFE/MAE calc error: {e}")

                # Запись в closed_trades.csv
                if CSVHandler:
                    try:
                        CSVHandler.log_closed_trade({
                            "timestamp": exit_ts,
                            "symbol": symbol,
                            "side": "EXIT",
                            "entry_price": entry_price,
                            "exit_price": float(actual_exit_price),
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

                # Уведомление о закрытии
                self._notify_close_safe(
                    symbol=symbol, price=float(actual_exit_price), reason=reason,
                    pnl_pct=float(pnl_pct), pnl_abs=float(pnl_abs),
                    buy_score=st.get("buy_score"), ai_score=st.get("ai_score"), amount_usd=qty_usd
                )

                # ✅ ОЧИЩАЕМ состояние позиции
                self._clear_position_state(actual_exit_price, reason)
                
                logging.info(f"✅ Позиция успешно закрыта: PnL {pnl_pct:.2f}% ({pnl_abs:.2f} USDT)")
                return True

            except Exception as e:
                logging.error(f"❌ close_all failed: {e}")
                # В критической ситуации принудительно закрываем
                self._force_close_position(symbol, exit_price, f"{reason}_critical_error")
                return None

    def _clear_position_state(self, exit_price: float, reason: str):
        """Очищает состояние позиции после успешного закрытия"""
        st = self.state.state
        st.update({
            "in_position": False,
            "opening": False,
            "close_price": float(exit_price),
            "last_reason": reason,
            "position_closed_at": datetime.utcnow().isoformat(),
            # Очищаем данные позиции
            "symbol": None,
            "entry_price": 0.0,
            "qty_usd": 0.0,
            "qty_base": 0.0,
            "buy_score": None,
            "ai_score": None,
            "final_score": None,
            "amount_frac": None,
            "tp_price_pct": 0.0,
            "sl_price_pct": 0.0,
            "tp1_atr": 0.0,
            "tp2_atr": 0.0,
            "sl_atr": 0.0,
            "trailing_on": False,
            "partial_taken": False,
        })
        self.state.save_state()

    def _force_close_position(self, symbol: str, exit_price: float, reason: str):
        """Принудительно закрывает позицию в случае критических ошибок"""
        logging.warning(f"⚠️ Force closing position: {reason}")
        try:
            self._notify_close_safe(
                symbol=symbol, price=float(exit_price), reason=reason,
                pnl_pct=0.0, pnl_abs=0.0
            )
        except Exception:
            pass
        self._clear_position_state(exit_price, reason)

    # ---------- manage ----------
    def manage(self, symbol: str, last_price: float, atr: float):
        """
        ✅ ИСПРАВЛЕНИЕ: Управление позицией с корректным отслеживанием стопов
        """
        with self._lock:
            st = self.state.state
            if not st.get("in_position"):
                return

            # Обновляем время последней проверки
            st["last_manage_check"] = datetime.utcnow().isoformat()

            entry = float(st.get("entry_price") or 0.0)
            tp_pct = float(st.get("tp_price_pct") or 0.0)
            sl_pct = float(st.get("sl_price_pct") or 0.0)
            tp1_atr = float(st.get("tp1_atr") or 0.0)
            tp2_atr = float(st.get("tp2_atr") or 0.0)
            sl_atr = float(st.get("sl_atr") or 0.0)
            trailing_on = bool(st.get("trailing_on"))
            partial_taken = bool(st.get("partial_taken"))

            if entry <= 0:
                logging.warning("⚠️ Invalid entry price in position, cannot manage")
                return

            current_pnl = (last_price - entry) / entry * 100.0
            logging.debug(f"📊 Managing position: price={last_price:.4f}, entry={entry:.4f}, PnL={current_pnl:.2f}%")

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем стоп-лоссы ПЕРВЫМИ
            stop_hit = False
            
            # Проверка процентного стоп-лосса
            if sl_pct > 0 and last_price <= sl_pct:
                logging.info(f"🛑 Stop Loss hit (PCT): {last_price:.4f} <= {sl_pct:.4f}")
                self.close_all(symbol, last_price, "SL_PCT_hit")
                stop_hit = True
                
            # Проверка ATR стоп-лосса  
            elif sl_atr > 0 and last_price <= sl_atr:
                logging.info(f"🛑 Stop Loss hit (ATR): {last_price:.4f} <= {sl_atr:.4f}")
                self.close_all(symbol, last_price, "SL_ATR_hit")
                stop_hit = True

            if stop_hit:
                return

            # ✅ ИСПРАВЛЕНИЕ: Проверяем тейк-профиты
            take_profit_hit = False
            
            # Основной тейк-профит (процентный)
            if tp_pct > 0 and last_price >= tp_pct:
                logging.info(f"🎯 Take Profit hit (PCT): {last_price:.4f} >= {tp_pct:.4f}")
                self.close_all(symbol, last_price, "TP_PCT_hit")
                take_profit_hit = True
                
            # ATR тейк-профит 2 (полное закрытие)
            elif tp2_atr > 0 and last_price >= tp2_atr:
                logging.info(f"🎯 Take Profit 2 hit (ATR): {last_price:.4f} >= {tp2_atr:.4f}")
                self.close_all(symbol, last_price, "TP2_ATR_hit")
                take_profit_hit = True

            if take_profit_hit:
                return

            # ✅ ИСПРАВЛЕНИЕ: Частичное закрытие на TP1 (только если не было частичного закрытия)
            if (not partial_taken) and tp1_atr > 0 and last_price >= tp1_atr:
                logging.info(f"🎯 TP1 ATR reached: {last_price:.4f} >= {tp1_atr:.4f}, attempting partial close")
                try:
                    qty_usd = float(st.get("qty_usd", 0.0))
                    qty_base_total = float(st.get("qty_base", 0.0))
                    qty_sell = qty_base_total / 2.0  # Продаем половину

                    # Проверяем минимальное количество для частичного закрытия
                    min_amount = self.ex.market_min_amount(symbol) or 0.0
                    if qty_sell < min_amount:
                        logging.info(f"⚠️ Partial close amount {qty_sell:.8f} < min {min_amount:.8f}, enabling trailing instead")
                        # Включаем трейлинг без частичного закрытия
                        st["trailing_on"] = True
                        st["partial_taken"] = True  # Помечаем как "частично закрыто" чтобы не повторять
                        if atr > 0:
                            new_sl_atr = max(entry, last_price - self.SL_ATR * atr)
                            new_sl_pct = max(entry, last_price * (1 + self.SL_PERCENT))
                            st["sl_atr"] = float(new_sl_atr)
                            st["sl_price_pct"] = float(new_sl_pct)
                        self.state.save_state()
                        return

                    # Выполняем частичное закрытие
                    qty_sell = self.ex.round_amount(symbol, qty_sell)
                    sell_order = self.ex.create_market_sell_order(symbol, qty_sell)
                    actual_sold = float(sell_order.get("filled", qty_sell))
                    
                    # Обновляем состояние позиции
                    remaining_qty_base = qty_base_total - actual_sold
                    remaining_qty_usd = remaining_qty_base * last_price
                    
                    st["qty_usd"] = float(remaining_qty_usd)
                    st["qty_base"] = float(remaining_qty_base)
                    st["partial_taken"] = True
                    st["trailing_on"] = True
                    
                   # Обновляем трейлинг
                    if atr > 0:
                        new_sl_atr = max(entry, last_price - self.SL_ATR * atr)
                        new_sl_pct = max(entry, last_price * (1 + self.SL_PERCENT))
                        st["sl_atr"] = float(new_sl_atr)
                        st["sl_price_pct"] = float(new_sl_pct)
                    
                    self.state.save_state()
                    
                    pnl_partial = (last_price - entry) / entry * 100.0
                    logging.info(f"✅ Partial close executed: sold {actual_sold:.8f} @ {last_price:.4f}, PnL {pnl_partial:.2f}%")
                    
                    # Уведомление о частичном закрытии
                    try:
                        from telegram import bot_handler as tgbot
                        tgbot.send_message(
                            f"📊 Частичное закрытие {symbol}\n"
                            f"Продано: {actual_sold:.8f} @ {last_price:.4f}\n"
                            f"PnL: {pnl_partial:.2f}%\n"
                            f"Остаток: {remaining_qty_base:.8f}\n"
                            f"Трейлинг активирован"
                        )
                    except Exception:
                        pass
                    
                except Exception as e:
                    logging.error(f"❌ Partial close failed: {e}")
                    # В случае ошибки все равно включаем трейлинг
                    st["trailing_on"] = True
                    st["partial_taken"] = True
                    if atr > 0:
                        new_sl_atr = max(entry, last_price - self.SL_ATR * atr)
                        new_sl_pct = max(entry, last_price * (1 + self.SL_PERCENT))
                        st["sl_atr"] = float(new_sl_atr)
                        st["sl_price_pct"] = float(new_sl_pct)
                    self.state.save_state()
                return

            # ✅ ИСПРАВЛЕНИЕ: Трейлинг стоп (только если включен)
            if trailing_on and atr > 0:
                current_sl_atr = float(st.get("sl_atr", 0.0))
                current_sl_pct = float(st.get("sl_price_pct", 0.0))
                
                # Рассчитываем новые уровни трейлинга
                new_sl_atr = last_price - self.SL_ATR * atr
                new_sl_pct = last_price * (1 + self.SL_PERCENT)
                
                # Обновляем только если новый стоп выше текущего (защита прибыли)
                sl_updated = False
                if new_sl_atr > current_sl_atr:
                    st["sl_atr"] = float(new_sl_atr)
                    sl_updated = True
                    
                if new_sl_pct > current_sl_pct:
                    st["sl_price_pct"] = float(max(entry, new_sl_pct))  # Не ниже точки входа
                    sl_updated = True
                
                if sl_updated:
                    self.state.save_state()
                    logging.debug(f"🔄 Trailing stop updated: SL_ATR={st['sl_atr']:.4f}, SL_PCT={st['sl_price_pct']:.4f}")

    def close_position(self, symbol: str, exit_price: float, reason: str):
        """Алиас для совместимости"""
        return self.close_all(symbol, exit_price, reason)