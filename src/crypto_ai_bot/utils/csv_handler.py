diff --git a/src/crypto_ai_bot/utils/csv_handler.py b/src/crypto_ai_bot/utils/csv_handler.py
index 0000000..0000001 100644
--- a/src/crypto_ai_bot/utils/csv_handler.py
+++ b/src/crypto_ai_bot/utils/csv_handler.py
@@ -9,6 +9,7 @@ from __future__ import annotations
 
 import os
 import csv
+from datetime import datetime
 import threading
 from typing import Dict, Any
 
@@ -55,5 +56,76 @@ class CSVHandler:
                 writer = csv.DictWriter(f, fieldnames=fields)
                 writer.writerow(safe_row or {})
 
+    @classmethod
+    def get_trade_stats(cls) -> Dict[str, Any]:
+        """
+        Р‘С‹СЃС‚СЂС‹Р№ РїРѕРґСЃС‡С‘С‚ СЃС‚Р°С‚РёСЃС‚РёРєРё РїРѕ С„Р°Р№Р»Сѓ Р·Р°РєСЂС‹С‚С‹С… СЃРґРµР»РѕРє (Р±РµР· pandas).
+        Р’РѕР·РІСЂР°С‰Р°РµС‚: {"count", "wins", "losses", "pnl_abs_sum", "last_ts"}.
+        """
+        cfg = Settings.load()
+        path = getattr(cfg, "CLOSED_TRADES_CSV", os.path.join("data", "closed_trades.csv"))
+        if not os.path.exists(path) or os.path.getsize(path) == 0:
+            return {"count": 0, "wins": 0, "losses": 0, "pnl_abs_sum": 0.0, "last_ts": None}
+
+        count = wins = losses = 0
+        pnl_sum = 0.0
+        last_dt = None
+
+        def _parse_iso(ts: str):
+            try:
+                if not ts:
+                    return None
+                ts = ts.replace("Z", "+00:00")
+                return datetime.fromisoformat(ts)
+            except Exception:
+                return None
+
+        def _to_float(v):
+            try:
+                return float(v)
+            except Exception:
+                return None
+
+        try:
+            with open(path, "r", encoding="utf-8") as f:
+                reader = csv.DictReader(f)
+                for row in reader:
+                    count += 1
+
+                    # pnl_abs / pnl_usd / pnl
+                    pnl = None
+                    for key in ("pnl_abs", "pnl_usd", "pnl"):
+                        v = _to_float(row.get(key))
+                        if v is not None:
+                            pnl = v
+                            break
+                    if pnl is not None:
+                        pnl_sum += pnl
+                        if pnl > 0:
+                            wins += 1
+                        elif pnl < 0:
+                            losses += 1
+                    else:
+                        # fall back РїРѕ Р·РЅР°РєСѓ РїСЂРѕС†РµРЅС‚Р°
+                        pct = _to_float(row.get("pnl_pct") or row.get("pnl_percent"))
+                        if pct is not None:
+                            if pct > 0:
+                                wins += 1
+                            elif pct < 0:
+                                losses += 1
+
+                    # РїРѕСЃР»РµРґРЅРёР№ С‚Р°Р№РјС€С‚Р°РјРї
+                    ts = (
+                        row.get("timestamp")
+                        or row.get("exit_ts")
+                        or row.get("close_ts")
+                        or row.get("close_datetime")
+                    )
+                    dt = _parse_iso(ts) if ts else None
+                    if dt and (last_dt is None or dt > last_dt):
+                        last_dt = dt
+        except Exception:
+            pass
+
+        return {
+            "count": count, "wins": wins, "losses": losses,
+            "pnl_abs_sum": round(pnl_sum, 2),
+            "last_ts": (last_dt.isoformat().replace("+00:00", "Z") if last_dt else None),
+        }
 
 __all__ = ["CSVHandler"]

