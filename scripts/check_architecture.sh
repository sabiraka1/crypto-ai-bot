#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Architecture checks starting in $ROOT"

failures=0
fail() { echo "✗ $*"; failures=$((failures+1)); }
pass() { echo "✓ $*"; }

# --- 1) ENV-правило: ENV читаем только в core/settings.py ---
# Дополнено: ловим os.getenv, os.environ[...], os.environ.get(...)
ENV_GREP=$(grep -RnE 'os\.(getenv\(|environ(\[|\.get\())' src || true)
if [[ -n "$ENV_GREP" ]]; then
  while IFS= read -r line; do
    file="${line%%:*}"
    if [[ "$file" != src/crypto_ai_bot/core/settings.py ]]; then
      fail "ENV read outside settings.py: $line"
    fi
  done <<< "$ENV_GREP"
else
  pass "No ENV reads outside settings.py"
fi

# --- 2) Запрет прямого requests.* (кроме utils/http_client.py) ---
REQ_GREP=$(grep -RnE '^\s*import\s+requests\b|^\s*from\s+requests\s+import\b|\brequests\.' src || true)
if [[ -n "$REQ_GREP" ]]; then
  while IFS= read -r line; do
    file="${line%%:*}"
    [[ "$file" == src/crypto_ai_bot/utils/http_client.py ]] && continue
    fail "Direct 'requests' usage: $line"
  done <<< "$REQ_GREP"
else
  pass "No direct 'requests' usage outside utils/http_client.py"
fi

# --- 3) Локальные _observe_hist (должны отсутствовать) ---
OBS_GREP=$(grep -Rn 'def\s+_observe_hist\(' src || true)
if [[ -n "$OBS_GREP" ]]; then
  while IFS= read -r line; do
    fail "Local _observe_hist duplicate — use utils.metrics helpers: $line"
  done <<< "$OBS_GREP"
else
  pass "No local _observe_hist found"
fi

# --- 4) utils/logging.py должен существовать и быть непустым ---
if [[ -s "src/crypto_ai_bot/utils/logging.py" ]]; then
  pass "utils/logging.py present"
else
  fail "utils/logging.py missing or empty"
fi

# --- 5) server.py не должен читать ENV (дублируем правило) ---
SRV_ENV=$(grep -nE 'os\.(getenv\(|environ(\[|\.get\())' src/crypto_ai_bot/app/server.py || true)
if [[ -n "$SRV_ENV" ]]; then
  fail "server.py must not read ENV: $SRV_ENV"
else
  pass "server.py has no direct ENV reads"
fi

# --- 6) Предупреждение о пустых .py ---
EMPTY=$(find src -type f -name "*.py" -size 0c || true)
if [[ -n "$EMPTY" ]]; then
  echo "⚠ Пустые python-файлы (рекомендуется заполнить или удалить):"
  echo "$EMPTY"
fi

# --- 7) Глубокие проверки (Python inline): импорты, события, хранилище, индикаторы, команды TG, эндпоинты ---
if ! PYTHONPATH=src python - <<'PY'; then
import importlib, traceback, sys, re, os
from pathlib import Path

root = Path(".").resolve()
pkg = root / "src" / "crypto_ai_bot"
errors = []

def fail(msg):
    print("PY ✗", msg); errors.append(msg)

def ok(msg):
    print("PY ✓", msg)

# 7.1 Smoke-import важных модулей
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

# 7.2 Events: AsyncEventBus + алиас AsyncBus
try:
    ev = importlib.import_module("crypto_ai_bot.core.events")
    aeb = hasattr(ev, "AsyncEventBus")
    alias = hasattr(ev, "AsyncBus")
    if aeb and alias:
        ok("events exports: AsyncEventBus (+ AsyncBus alias)")
    else:
        fail(f"events exports mismatch: AsyncEventBus={aeb}, AsyncBus={alias}")
except Exception as e:
    fail(f"events import error: {e}")

# 7.3 Storage: in_txn, SqliteUnitOfWork, connect
try:
    st = importlib.import_module("crypto_ai_bot.core.storage")
    has_txn = hasattr(st, "in_txn")
    has_uow = hasattr(st, "SqliteUnitOfWork")
    has_conn = hasattr(st, "connect")
    if has_txn and has_uow and has_conn:
        ok("storage exports: in_txn, SqliteUnitOfWork, connect")
    else:
        fail(f"storage exports mismatch: in_txn={has_txn}, SqliteUnitOfWork={has_uow}, connect={has_conn}")
except Exception as e:
    fail(f"storage import error: {e}")

# 7.4 Indicators: build_indicators
try:
    ind = importlib.import_module("crypto_ai_bot.core.indicators.unified")
    if hasattr(ind, "build_indicators"):
        ok("indicators: build_indicators present")
    else:
        fail("indicators: build_indicators missing")
except Exception as e:
    fail(f"indicators import error: {e}")

# 7.5 Telegram: ровно /help /status /test /profit /eval /why; нет /buy|/sell
tg = pkg / "app" / "adapters" / "telegram.py"
need = {"/help", "/status", "/test", "/profit", "/eval", "/why"}
if tg.exists():
    txt = tg.read_text(encoding="utf-8", errors="ignore")
    present = {c for c in need if c in txt}
    bad = [c for c in ("/buy","/sell") if c in txt]
    if present == need and not bad:
        ok("telegram commands set: OK")
    else:
        miss = sorted(list(need - present))
        if miss: fail(f"telegram missing commands: {miss}")
        if bad:  fail(f"telegram forbidden commands present: {bad}")
else:
    fail("adapters/telegram.py not found")

# 7.6 Endpoints: /health /metrics /status/extended и /telegram|/telegram/webhook
paths = set()
try:
    srv = importlib.import_module("crypto_ai_bot.app.server")
    app = getattr(srv, "app", None)
    if app is not None:
        try:
            from starlette.routing import Route
            for r in app.routes:
                if isinstance(r, Route):
                    paths.add(r.path)
        except Exception:
            pass
except Exception as e:
    # если не удалось импортировать app, попробуем парсинг исходника
    pass

if not paths:
    sfile = pkg / "app" / "server.py"
    if sfile.exists():
        stext = sfile.read_text(encoding="utf-8", errors="ignore")
        for p in ("/health","/metrics","/status/extended","/telegram","/telegram/webhook"):
            if p in stext: paths.add(p)

missing = {"/health","/metrics","/status/extended"}
has_tel = any("/telegram" in p for p in paths)
miss = {p for p in missing if p not in paths}
if not miss and has_tel:
    ok("endpoints: /health /metrics /status/extended and telegram route present")
else:
    if miss:  fail(f"endpoints missing: {sorted(list(miss))}")
    if not has_tel: fail("telegram endpoint missing (/telegram or /telegram/webhook)")

# Итог
if errors:
    print("PY ==== summary ====")
    for e in errors: print("PY -", e)
    sys.exit(1)
else:
    sys.exit(0)
PY
then
  pass "Deep Python smoke checks"
else
  fail "Deep Python smoke checks failed"
fi

# --- Итог ---
if [[ $failures -gt 0 ]]; then
  echo "==> FAILED ($failures problems)"; exit 1
else
  echo "==> OK"; exit 0
fi
