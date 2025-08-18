#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Architecture checks starting in $ROOT"
export PYTHONPATH=src

# 1) ENV-правило (только через core/settings.py)
#   - игнорим __pycache__, .venv, .git; не читаем бинарники
ENV_GREP=$(grep -RnEI --binary-files=without-match -I \
  --exclude-dir='__pycache__' --exclude-dir='.venv' --exclude-dir='.git' \
  'os\.(getenv\(|environ(\[|\.get\())' src || true)
if [[ -n "$ENV_GREP" ]]; then
  fail=0
  while IFS= read -r line; do
    file="${line%%:*}"
    if [[ "$file" != src/crypto_ai_bot/core/settings.py ]]; then
      echo "✗ ENV read outside settings.py: $line"
      fail=1
    fi
  done <<< "$ENV_GREP"
  [[ $fail -eq 0 ]] && echo "✓ No ENV reads outside settings.py"
else
  echo "✓ No ENV reads outside settings.py"
fi

# 2) Запрет прямого requests.* (кроме utils/http_client.py)
REQ_GREP=$(grep -RnEI --binary-files=without-match -I \
  --exclude-dir='__pycache__' --exclude-dir='.venv' --exclude-dir='.git' \
  '^\s*import\s+requests\b|^\s*from\s+requests\s+import\b|\brequests\.' src || true)
if [[ -n "$REQ_GREP" ]]; then
  fail=0
  while IFS= read -r line; do
    file="${line%%:*}"
    [[ "$file" == src/crypto_ai_bot/utils/http_client.py ]] && continue
    echo "✗ Direct 'requests' usage: $line"
    fail=1
  done <<< "$REQ_GREP"
  [[ $fail -eq 0 ]] && echo "✓ No direct 'requests' usage outside utils/http_client.py"
else
  echo "✓ No direct 'requests' usage outside utils/http_client.py"
fi

# 3) utils/logging.py должен существовать (не пустой)
if [[ -s "src/crypto_ai_bot/utils/logging.py" ]]; then
  echo "✓ utils/logging.py present"
else
  echo "✗ utils/logging.py missing or empty"; exit 1
fi

# 4) Пустые файлы (информативно)
EMPTY=$(find src -type f -name "*.py" -size 0c -not -path "*/__pycache__/*" || true)
[[ -n "$EMPTY" ]] && echo "⚠ Empty python files:" && echo "$EMPTY"

# 5) Глубокие проверки — отдельным Python-скриптом (стабильно в Git Bash)
python scripts/arch_smoke.py
echo "==> OK"
