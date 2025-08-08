diff --git a/trading/position_manager.py b/trading/position_manager.py
index 10d0103d18874bfad78e1fc583c44f45122279e2..b3c7a36974e1f54a2460e10a3ef2a2c8f8a23cc8 100644
--- a/trading/position_manager.py
+++ b/trading/position_manager.py
@@ -1,39 +1,46 @@
 import os
 import logging
 from datetime import datetime
 
+from config.settings import TradingConfig
+
 # Безопасная работа с CSV
 try:
     from utils.csv_handler import CSVHandler
 except Exception:
     CSVHandler = None
 
 
+CFG = TradingConfig()
+
+
 class PositionManager:
-    TP_PERCENT = 0.02   # 2% тейк-профит
-    SL_PERCENT = -0.02  # -2% стоп-лосс
+    """Управление открытой позицией"""
+
+    TP_PERCENT = CFG.TAKE_PROFIT_PCT / 100  # тейк-профит в долях
+    SL_PERCENT = -CFG.STOP_LOSS_PCT / 100  # стоп-лосс в долях
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
diff --git a/trading/position_manager.py b/trading/position_manager.py
index 10d0103d18874bfad78e1fc583c44f45122279e2..b3c7a36974e1f54a2460e10a3ef2a2c8f8a23cc8 100644
--- a/trading/position_manager.py
+++ b/trading/position_manager.py
@@ -102,48 +109,86 @@ class PositionManager:
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
 
-    # ========= УПРАВЛЕНИЕ ПОЗИЦИЕЙ (добавлен недостающий метод) =========
-    def manage(self, symbol: str, current_price: float, atr: float):
-        """Метод для управления открытой позицией (трейлинг, частичное закрытие)"""
+    # ========= УПРАВЛЕНИЕ ПОЗИЦИЕЙ =========
+    def manage(self, symbol: str, last_price: float, atr: float):
+        """Сопровождение позиции: трейлинг, тейк-профит, стоп-лосс"""
+
         st = self.state.state
-        if not st.get('in_position'):
+        if not st.get("in_position"):
+            return
+
+        # --- Достаём необходимые значения ---
+        entry = float(st.get("entry_price") or 0.0)
+        tp_pct = float(st.get("tp_price_pct") or 0.0)
+        sl_pct = float(st.get("sl_price_pct") or 0.0)
+        tp1_atr = float(st.get("tp1_atr") or 0.0)
+        tp2_atr = float(st.get("tp2_atr") or 0.0)
+        sl_atr = float(st.get("sl_atr") or 0.0)
+        trailing_on = bool(st.get("trailing_on"))
+        partial_taken = bool(st.get("partial_taken"))
+
+        if entry <= 0:
+            return
+
+        # --- Стоп-лосс ---
+        if (sl_pct and last_price <= sl_pct) or (sl_atr and last_price <= sl_atr):
+            self.close_all(symbol, last_price, "SL_hit")
+            return
+
+        # --- Тейк-профит (полный выход) ---
+        if (tp_pct and last_price >= tp_pct) or (tp2_atr and last_price >= tp2_atr):
+            self.close_all(symbol, last_price, "TP_hit")
             return
 
-        entry_price = float(st.get('entry_price', 0))
-        if entry_price <= 0:
+        # --- Частичное закрытие и включение трейлинга ---
+        if (not partial_taken) and tp1_atr and last_price >= tp1_atr:
+            qty_total = float(st.get("qty_usd", 0.0)) / last_price
+            qty_sell = qty_total / 2
+            try:
+                self.ex.create_market_sell_order(symbol, qty_sell)
+            except Exception as e:
+                logging.error(f"❌ Partial close failed: {e}")
+            else:
+                st["qty_usd"] = float(st.get("qty_usd", 0.0)) / 2
+                st["partial_taken"] = True
+                st["trailing_on"] = True
+                # переносим SL на безубыток или выше
+                st["sl_atr"] = max(entry, last_price - self.SL_ATR * atr)
+                st["sl_price_pct"] = max(entry, last_price * (1 + self.SL_PERCENT))
+                self.state.save_state()
             return
 
-        # Простая логика: если цена выросла на 4%, закрываем
-        pnl_pct = (current_price - entry_price) / entry_price * 100.0
-        
-        if pnl_pct >= 4.0:  # 4% прибыль
-            self.close_all(symbol, current_price, "TP_4%")
-        elif pnl_pct <= -3.0:  # -3% убыток
-            self.close_all(symbol, current_price, "SL_3%")
+        # --- Трейлинг стоп ---
+        if trailing_on:
+            new_sl_atr = last_price - self.SL_ATR * atr
+            if new_sl_atr > sl_atr:
+                st["sl_atr"] = new_sl_atr
+                st["sl_price_pct"] = max(st["sl_price_pct"], last_price * (1 + self.SL_PERCENT))
+                self.state.save_state()
 
     # ========= АЛЬТЕРНАТИВНОЕ ИМЯ МЕТОДА (для совместимости) =========
     def close_position(self, symbol: str, exit_price: float, reason: str):
         """Альтернативное имя для close_all (для совместимости)"""
         self.close_all(symbol, exit_price, reason)
