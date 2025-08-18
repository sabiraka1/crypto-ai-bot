#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Architecture sanity check =="

# 1) Пустые (кроме __init__.py)
echo "-- Empty / near-empty python files:"
EMPTY=$(find src -type f -name "*.py" ! -name "__init__.py" -exec awk 'BEGIN{empty=1} { if (length($0) > 1 && $0 !~ /^[[:space:]]*#/) empty=0 } END{ if (empty) print FILENAME }' {} + || true)
if [[ -n "${EMPTY:-}" ]]; then
  echo "$EMPTY"
  echo "✗ Found empty stubs ↑"
else
  echo "✓ none"
fi

# 2) Критичные файлы присутствуют
echo "-- Critical files presence:"
CRIT=0
for p in \
  "src/crypto_ai_bot/app/server.py" \
  "src/crypto_ai_bot/utils/rate_limit.py" \
  "src/crypto_ai_bot/utils/metrics.py" \
  "src/crypto_ai_bot/utils/logging.py" \
  "src/crypto_ai_bot/core/events/bus.py" \
  "src/crypto_ai_bot/core/events/async_bus.py" \
  "src/crypto_ai_bot/core/events/factory.py" \
  "src/crypto_ai_bot/core/use_cases/evaluate.py" \
  "src/crypto_ai_bot/core/use_cases/place_order.py" \
  "src/crypto_ai_bot/core/storage/sqlite_adapter.py"
do
  if [[ -f "$p" ]]; then
    echo "✓ $p"
  else
    echo "✗ missing: $p"; CRIT=1
  fi
done

echo "-- Hints:"
echo "• Run 'uvicorn crypto_ai_bot.app.server:app --reload' and check /health, /status/extended, /metrics, /context."
echo "• PERF_BUDGET_*_P99_MS envs enable budget flags."
exit $CRIT
