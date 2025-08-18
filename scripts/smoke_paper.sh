#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-http://127.0.0.1:8000}"
SYMBOL="${SYMBOL:-BTC/USDT}"
TF="${TF:-1h}"
LIMIT="${LIMIT:-100}"
N="${N:-10}"

echo "== Smoke (paper) =="
echo "Host: $HOST"
echo "Symbol=$SYMBOL TF=$TF Limit=$LIMIT N=$N"
echo

ok=0
blocked=0
hold=0
rate=0
err=0

t0=$(date +%s%3N)

for i in $(seq 1 "$N"); do
  ts=$(date +%s%3N)
  out=$(curl -s -X POST "$HOST/tick" \
      -H "Content-Type: application/json" \
      -H "X-Request-Id: smoke-$ts-$i" \
      -d "{\"symbol\":\"$SYMBOL\",\"timeframe\":\"$TF\",\"limit\":$LIMIT}" || true)
  status=$(echo "$out" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p' | head -n1)
  case "$status" in
    ok) ok=$((ok+1));;
    blocked_by_risk) blocked=$((blocked+1));;
    hold) hold=$((hold+1));;
    rate_limited) rate=$((rate+1));;
    *) err=$((err+1));;
  esac
  echo "[$i/$N] status=${status:-unknown}"
done

t1=$(date +%s%3N)
dt=$((t1 - t0))
avg=$(awk "BEGIN { if ($N>0) print $dt/$N; else print 0 }")

echo
echo "== Summary =="
echo "ok=$ok  blocked_by_risk=$blocked  hold=$hold  rate_limited=$rate  error=$err"
echo "total_ms=$dt  avg_ms_per_call=$(printf '%.1f' "$avg")"
