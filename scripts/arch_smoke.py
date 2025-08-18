# -*- coding: ascii -*-
from __future__ import annotations
import os, sys, re, importlib, traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
PKG = SRC / "crypto_ai_bot"

def fail(msg): 
    print("[FAIL]", msg)
    failures.append(msg)

def ok(msg):   
    print("[ OK ]", msg)

def grep_sources(pattern: str, exclude=None):
    rx = re.compile(pattern)
    hits = []
    for p in SRC.rglob("*.py"):
        if exclude and any(str(p).startswith(str(e)) for e in exclude):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if rx.search(txt):
            hits.append(p)
    return hits

def rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))

failures = []
os.environ.setdefault("PYTHONPATH", "src")

# 0) Required nodes exist
must = [
    PKG/"app/server.py", PKG/"app/middleware.py", PKG/"app/bus_wiring.py",
    PKG/"app/adapters/telegram.py",
    PKG/"core/settings.py", PKG/"core/use_cases/evaluate.py",
    PKG/"core/use_cases/place_order.py", PKG/"core/signals/policy.py",
    PKG/"core/indicators/unified.py", PKG/"core/brokers",
    PKG/"core/events", PKG/"core/storage",
    PKG/"utils/metrics.py", PKG/"utils/http_client.py",
]
missing = [rel(p) for p in must if not p.exists()]
if not missing:
    ok("Structure: required nodes present")
else:
    fail("Structure: missing: " + ", ".join(missing))

# 1) Smoke imports
mods = [
  "crypto_ai_bot.core.events",
  "crypto_ai_bot.core.events.async_bus",
  "crypto_ai_bot.core.brokers.base",
  "crypto_ai_bot.core.storage",
  "crypto_ai_bot.core.storage.repositories.idempotency",
  "crypto_ai_bot.core.indicators.unified",
  "crypto_ai_bot.core.use_cases.evaluate",
  "crypto_ai_bot.app.server",
]
for m in mods:
    try:
        importlib.import_module(m)
        ok(f"import {m}")
    except Exception:
        fail(f"import failed: {m}\n{traceback.format_exc()}")

# 2) Events exports
try:
    ev = importlib.import_module("crypto_ai_bot.core.events")
    aeb, alias = hasattr(ev, "AsyncEventBus"), hasattr(ev, "AsyncBus")
    if aeb and alias:
        ok("events exports: AsyncEventBus (+ AsyncBus alias)")
    else:
        fail(f"events exports mismatch: AsyncEventBus={aeb}, AsyncBus={alias}")
except Exception as e:
    fail(f"events import error: {e}")

# 3) Storage exports
try:
    st = importlib.import_module("crypto_ai_bot.core.storage")
    tx, uow, conn = hasattr(st, "in_txn"), hasattr(st, "SqliteUnitOfWork"), hasattr(st, "connect")
    if tx and uow and conn:
        ok("storage exports: in_txn, SqliteUnitOfWork, connect")
    else:
        fail(f"storage exports mismatch: in_txn={tx}, SqliteUnitOfWork={uow}, connect={conn}")
except Exception as e:
    fail(f"storage import error: {e}")

# 4) Indicators
try:
    ind = importlib.import_module("crypto_ai_bot.core.indicators.unified")
    if hasattr(ind, "build_indicators"):
        ok("indicators: build_indicators present")
    else:
        fail("indicators: build_indicators missing")
except Exception as e:
    fail(f"indicators import error: {e}")

# 5) Telegram commands
tg = PKG / "app" / "adapters" / "telegram.py"
need = {"/help","/status","/test","/profit","/eval","/why"}
if tg.exists():
    txt = tg.read_text(encoding="utf-8", errors="ignore")
    present = {c for c in need if c in txt}
    bad = [c for c in ("/buy","/sell") if c in txt]
    if present == need and not bad:
        ok("telegram commands set: OK")
    else:
        if need - present: fail("telegram missing: " + ", ".join(sorted(list(need-present))))
        if bad:           fail("telegram forbidden: " + ", ".join(bad))
else:
    fail("adapters/telegram.py not found")

# 6) Endpoints
paths = set()
try:
    srv = importlib.import_module("crypto_ai_bot.app.server")
    app = getattr(srv, "app", None)
    if app is not None:
        from starlette.routing import Route
        for r in app.routes:
            if isinstance(r, Route):
                paths.add(r.path)
except Exception:
    pass
if not paths:
    s = (PKG / "app" / "server.py").read_text(encoding="utf-8", errors="ignore")
    for p in ("/health","/metrics","/status/extended","/telegram","/telegram/webhook"):
        if p in s:
            paths.add(p)
missing = {p for p in ("/health","/metrics","/status/extended") if p not in paths}
has_tel = any("/telegram" in p for p in paths)
if not missing and has_tel:
    ok("endpoints: /health /metrics /status/extended + /telegram present")
else:
    if missing: fail("endpoints missing: " + ", ".join(sorted(list(missing))))
    if not has_tel: fail("telegram endpoint missing")

print()
if failures:
    print("SUMMARY: FAIL")
    for f in failures:
        print("-", f)
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
