#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export TRADER_AUTOSTART="${TRADER_AUTOSTART:-1}"
exec uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port "${PORT:-8000}"
