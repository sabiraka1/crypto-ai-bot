diff --git a/app.py b/app.py
index 58be93b6674dfcece06954c9e6ffd13aa86cedbc..085ac935dbfe11cf3a72daf4896c65eba44f7cff 100644
--- a/app.py
+++ b/app.py
@@ -1,43 +1,116 @@
 import os
 import logging
 import threading
 from flask import Flask, request, jsonify
 
 from main import TradingBot
 from core.state_manager import StateManager
 from trading.exchange_client import ExchangeClient
 from telegram.bot_handler import (
-    cmd_start, cmd_status, cmd_profit, cmd_errors, cmd_lasttrades, cmd_train, cmd_test, cmd_testbuy, cmd_testsell
+    cmd_start,
+    cmd_status,
+    cmd_profit,
+    cmd_errors,
+    cmd_lasttrades,
+    cmd_train,
+    cmd_test,
+    cmd_testbuy,
+    cmd_testsell,
 )
 
+
 # --- тихий /train: не падаем, если нужны X/y ---
-def _train_model_safe():
+def _train_model_safe() -> bool:
     try:
+        import pandas as pd
+        from analysis.technical_indicators import TechnicalIndicators
+        from analysis.market_analyzer import MultiTimeframeAnalyzer
         from ml.adaptive_model import AdaptiveMLModel
-        AdaptiveMLModel().train()
-        return True
+
+        symbol = os.getenv("SYMBOL", "BTC/USDT")
+        timeframe = os.getenv("TIMEFRAME", "15m")
+
+        ex = _GLOBAL_EX
+
+        # Загружаем исторические данные
+        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=500)
+        if not ohlcv:
+            logging.error("No OHLCV data for training")
+            return False
+
+        cols = ["time", "open", "high", "low", "close", "volume"]
+        df_raw = pd.DataFrame(ohlcv, columns=cols)
+        df_raw["time"] = pd.to_datetime(df_raw["time"], unit="ms", utc=True)
+        df_raw.set_index("time", inplace=True)
+
+        # Рассчитываем индикаторы
+        df = TechnicalIndicators.calculate_all_indicators(df_raw.copy())
+        df["price_change"] = df["close"].pct_change()
+        df["future_close"] = df["close"].shift(-1)
+        df["y"] = (df["future_close"] > df["close"]).astype(int)
+        df.dropna(inplace=True)
+
+        feature_cols = [
+            "rsi",
+            "macd",
+            "ema_cross",
+            "bb_position",
+            "stoch_k",
+            "adx",
+            "volume_ratio",
+            "price_change",
+        ]
+
+        if any(col not in df.columns for col in feature_cols) or df.empty:
+            logging.error("Not enough features for training")
+            return False
+
+        X = df[feature_cols].to_numpy()
+        y = df["y"].to_numpy()
+
+        # Анализ рыночных условий
+        analyzer = MultiTimeframeAnalyzer()
+        agg = {
+            "open": "first",
+            "high": "max",
+            "low": "min",
+            "close": "last",
+            "volume": "sum",
+        }
+        df_1d = df_raw.resample("1D").agg(agg)
+        df_4h = df_raw.resample("4H").agg(agg)
+
+        market_conditions: list[str] = []
+        for idx in df.index:
+            cond, _ = analyzer.analyze_market_condition(
+                df_1d.loc[:idx], df_4h.loc[:idx]
+            )
+            market_conditions.append(cond.value)
+
+        model = AdaptiveMLModel()
+        return model.train(X, y, market_conditions)
     except Exception as e:
         logging.error("train error: %s", e)
         return False
 
 # --- логирование ---
 logging.basicConfig(
     level=logging.INFO,
     format="%(asctime)s %(levelname)s %(message)s",
     handlers=[
         logging.StreamHandler(),
         logging.FileHandler("bot_activity.log", encoding="utf-8"),
     ],
 )
 
 app = Flask(__name__)
 
 # --- единый ExchangeClient (singleton для процесса) ---
 _GLOBAL_EX = ExchangeClient()
 
 # --- домашняя страница/health ---
 @app.route("/health", methods=["GET"])
 def health():
     return jsonify({"ok": True, "status": "running"}), 200
 
 @app.route("/", methods=["GET"])
