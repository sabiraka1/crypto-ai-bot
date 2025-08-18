#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Architecture checks starting in $ROOT"

failures=0
fail() { echo "✗ $*"; failures=$((failures+1)); }

pass() { echo "✓ $*"; }

# 1) ENV-правило: os.getenv разрешён только в core/settings.py
ENV_GREP=$(grep -Rn "os\.getenv\(" src || true)
if [[ -n "$ENV_GREP" ]]; then
  while IFS= read -r line; do
    file="${line%%:*}"
    if [[ "$file" != src/crypto_ai_bot/core/settings.py ]]; then
      fail "ENV read outside settings.py: $line"
    fi
  done <<< "$ENV_GREP"
else
  pass "No ENV reads found"
fi

# 2) Запрет прямого requests — должен использоваться utils/http_client.py
REQ_GREP=$(grep -RnE "^\s*import\s+requests\b|^\s*from\s+requests\s+import\b" src || true)
if [[ -n "$REQ_GREP" ]]; then
  while IFS= read -r line; do
    # Разрешим внутри utils/http_client.py (если он сам импортит requests)
    file="${line%%:*}"
    if [[ "$file" != src/crypto_ai_bot/utils/http_client.py ]]; then
      fail "Direct 'requests' usage: $line"
    fi
  done <<< "$REQ_GREP"
else
  pass "No direct 'requests' imports found"
fi

# 3) Локальные _observe_hist — должны быть удалены
OBS_GREP=$(grep -Rn "def\s+_observe_hist\(" src || true)
if [[ -n "$OBS_GREP" ]]; then
  while IFS= read -r line; do
    fail "Local _observe_hist duplicate — use utils.metrics.observe_histogram/observe_ms: $line"
  done <<< "$OBS_GREP"
else
  pass "No local _observe_hist found"
fi

# 4) utils/logging.py должен существовать и быть непустым
if [[ -s "src/crypto_ai_bot/utils/logging.py" ]]; then
  pass "utils/logging.py present"
else
  fail "utils/logging.py missing or empty"
fi

# 5) server.py не должен читать ENV
SRV_ENV=$(grep -n "os\.getenv\(" src/crypto_ai_bot/app/server.py || true)
if [[ -n "$SRV_ENV" ]]; then
  fail "server.py must not read ENV: $SRV_ENV"
else
  pass "server.py has no ENV reads"
fi

# 6) Бонус: подсказка по пустым файлам (warning)
EMPTY=$(find src -type f -name "*.py" -size 0c || true)
if [[ -n "$EMPTY" ]]; then
  echo "⚠ Пустые python-файлы (рекомендуется заполнить или удалить):"
  echo "$EMPTY"
fi

if [[ $failures -gt 0 ]]; then
  echo "==> FAILED ($failures problems)"; exit 1
else
  echo "==> OK"; exit 0
fi
