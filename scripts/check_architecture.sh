#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/src/crypto_ai_bot"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

fail=0

note()  { echo "• $*"; }
bad()   { red "✗ $*"; fail=1; }
good()  { green "✓ $*"; }

# 1) os.getenv — только в core/settings.py
note "Проверка: os.getenv только в core/settings.py"
if grep -RIn --exclude-dir=__pycache__ -E "os\.getenv\(" "$SRC" | grep -v "core/settings.py" >/dev/null; then
  bad "Обнаружен os.getenv вне core/settings.py:"
  grep -RIn --exclude-dir=__pycache__ -E "os\.getenv\(" "$SRC" | grep -v "core/settings.py"
else
  good "os.getenv — OK"
fi

# 2) Запрет прямого requests.* вне utils/http_client.py
note "Проверка: requests.* только через utils/http_client.py"
if grep -RIn --exclude-dir=__pycache__ -E "\brequests\." "$SRC" | grep -v "utils/http_client.py" >/dev/null; then
  bad "Обнаружены прямые requests.*:"
  grep -RIn --exclude-dir=__pycache__ -E "\brequests\." "$SRC" | grep -v "utils/http_client.py"
else
  good "requests.* — OK"
fi

# 3) Приватные сигналы core/signals/_*.py — импортируются только из policy.py
note "Проверка: приватные helpers core/signals/_*.py"
if grep -RIn --exclude-dir=__pycache__ -E "core\.signals\._" "$SRC" | grep -v "core/signals/policy.py" >/dev/null; then
  bad "Импорты core.signals._* вне policy.py:"
  grep -RIn --exclude-dir=__pycache__ -E "core\.signals\._" "$SRC" | grep -v "core/signals/policy.py"
else
  good "core.signals._* — OK"
fi

# 4) Индикаторы — только unified.py
note "Проверка: индикаторы — только core/indicators/unified.py"
if grep -RIn --exclude-dir=__pycache__ -E "(talib|ta\.)" "$SRC" >/dev/null; then
  bad "Найдены сторонние вызовы индикаторов (talib/ta.*). Разрешён только unified.py."
  grep -RIn --exclude-dir=__pycache__ -E "(talib|ta\.)" "$SRC"
else
  good "Индикаторы — OK"
fi

# 5) Запрет импорта analysis/ и market_context/ из core/*
note "Проверка: core/* не импортирует analysis/ и market_context/"
if grep -RIn --exclude-dir=__pycache__ -E "from crypto_ai_bot\.(analysis|market_context)\." "$SRC/core" >/dev/null; then
  bad "core/* импортирует analysis/ или market_context/:"
  grep -RIn --exclude-dir=__pycache__ -E "from crypto_ai_bot\.(analysis|market_context)\." "$SRC/core"
else
  good "Импорты core/* — OK"
fi

# 6) В policy.py должен присутствовать блок time_drift
note "Проверка: policy.py содержит блок time_drift"
if ! grep -RIn --exclude-dir=__pycache__ -E "time_drift" "$SRC/core/signals/policy.py" >/dev/null; then
  bad "В policy.py не найдено упоминаний time_drift"
else
  good "time_drift в policy.py — OK"
fi

if [[ $fail -eq 0 ]]; then
  green "Все проверки пройдены ✅"
  exit 0
else
  red "Есть нарушения ❌"
  exit 1
fi
