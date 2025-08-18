# scripts/check_architecture.sh
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Architecture sanity check =="

# 1) Пустые или почти пустые (кроме __init__.py)
echo "-- Empty / nearly-empty python files:"
NEAR_EMPTY=$( \
  find src -type f -name "*.py" ! -name "__init__.py" \
  -exec awk '
    BEGIN{nonblank=0}
    {
      line=$0
      # считаем «содержательной» строкой то, что не только пробелы/комменты
      if (line !~ /^[[:space:]]*$/ && line !~ /^[[:space:]]*#/) nonblank++
    }
    END{
      if (nonblank <= 3) print FILENAME
    }' {} + \
)
if [[ -n "${NEAR_EMPTY:-}" ]]; then
  echo "$NEAR_EMPTY"
  echo "✗ Found empty/nearly-empty stubs ↑"
else
  echo "✓ none"
fi

# 2) Критичные файлы присутствуют
echo "-- Critical files presence:"
CRIT=0
for p in \
  "src/crypto_ai_bot/app/server.py" \
  "src/crypto_ai_bot/utils/metrics.py" \
  "src/crypto_ai_bot/utils/logging.py" \
  "src/crypto_ai_bot/utils/rate_limit.py" \
  "src/crypto_ai_bot/core/events/async_bus.py" \
  "src/crypto_ai_bot/core/events/factory.py" \
  "src/crypto_ai_bot/core/use_cases/evaluate.py" \
  "src/crypto_ai_bot/core/use_cases/place_order.py" \
  "src/crypto_ai_bot/core/use_cases/eval_and_execute.py" \
  "src/crypto_ai_bot/core/brokers/ccxt_exchange.py" \
  "src/crypto_ai_bot/core/storage/sqlite_adapter.py"
do
  if [[ -f "$p" ]]; then
    echo "✓ $p"
  else
    echo "✗ missing: $p"; CRIT=1
  fi
done

echo "-- Tips:"
echo "• Run 'uvicorn crypto_ai_bot.app.server:app --reload' and check /health, /status/extended, /metrics, /context."
echo "• Use '.env.example' as canonical env template."
exit $CRIT
