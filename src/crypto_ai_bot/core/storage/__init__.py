- import sqlite3
- import os
+ import sqlite3
+ from crypto_ai_bot.core.settings import Settings
  from contextlib import contextmanager

@@
-try:
-    from .sqlite_adapter import connect  # type: ignore
-except Exception:
-    def connect(db_path: str | None = None, **kwargs) -> sqlite3.Connection:
-        path = db_path or os.getenv("DB_PATH", ":memory:")
-        conn = sqlite3.connect(path, check_same_thread=False)
-        conn.row_factory = sqlite3.Row
-        return conn
+try:
+    from .sqlite_adapter import connect  # type: ignore
+except Exception:
+    def connect(db_path: str | None = None, **kwargs) -> sqlite3.Connection:
+        """Fallback: берём путь из Settings (а не напрямую из ENV), иначе ':memory:'."""
+        if db_path is None:
+            try:
+                cfg = Settings()
+                path = getattr(cfg, "DB_PATH", ":memory:")
+            except Exception:
+                path = ":memory:"
+        else:
+            path = db_path
+        conn = sqlite3.connect(path, check_same_thread=False)
+        conn.row_factory = sqlite3.Row
+        return conn
