#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Architecture sanity check =="
cd "$ROOT"

# 1) Пустые или почти пустые файлы (< 10 байт или только перенос)
echo "-- Empty / near-empty files:"
EMPTY=$(find src -type f -name "*.py" -exec awk 'BEGIN{empty=1} { if (length($0) > 1 && $0 !~ /^[[:space:]]*#/) empty=0 } END{ if (empty) print FILENAME }' {} + || true)
if [[ -n "${EMPTY:-}" ]]; then
  echo "$EMPTY"
  echo "✗ Found empty stubs ↑"
else
  echo "✓ none"
fi

# 2) Критичные пути и файлы
echo "-- Critical files presence:"
CRIT=0
for p in \
  "src/crypto_ai_bot/utils/logging.py" \
  "src/crypto_ai_bot/utils/metrics.py" \
  "src/crypto_ai_bot/app/server.py" \
  "src/crypto_ai_bot/core/storage/sqlite_adapter.py" \
  "src/crypto_ai_bot/core/events/bus.py" \
  "src/crypto_ai_bot/core/use_cases/evaluate.py" \
  "src/crypto_ai_bot/core/use_cases/place_order.py" \
  "src/crypto_ai_bot/core/use_cases/eval_and_execute.py"
do
  if [[ -f "$p" ]]; then
    echo "✓ $p"
  else
    echo "✗ missing: $p"; CRIT=1
  fi
done

# 3) Быстрые подсказки
echo "-- Hints:"
echo "• Ensure TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID for alerts (optional)."
echo "• Run 'uvicorn crypto_ai_bot.app.server:app --reload' and check /health, /metrics."
echo "• Set PERF_BUDGET_*_P99_MS to enable budget flags."

exit $CRIT
