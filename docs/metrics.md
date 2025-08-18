\# Метрики crypto-ai-bot (Prometheus)



Этот файл — практичная шпаргалка: \*\*какие метрики есть\*\*, какие лейблы допустимы (низкая кардинальность), \*\*как читать p95/p99\*\*, и примеры запросов в Prometheus/Grafana.



\## Конвенции



\- \*\*snake\_case\*\* для имён, короткие и стабильные лейблы.

\- Избегаем высокой кардинальности:

&nbsp; - `method` ∈ {GET, POST, ...}

&nbsp; - `path` — только шаблоны вроде `/tick`, `/health` (без raw id).

&nbsp; - `type`, `key`, `reason`, `strategy`, `exchange`, `code` — короткие значения.

\- Гистограммы используют единые бакеты (секунды):  

&nbsp; `0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7.5, 10, +Inf`



---



\## Каталог метрик



\### 1) HTTP (app/middleware)



\- `http\_requests\_total{method,path,code}` — счётчик запросов.

\- `http\_request\_duration\_seconds{method,path}` — гистограмма длительности.



\*\*Примеры\*\*

```promql

sum by (code) (rate(http\_requests\_total\[5m]))

histogram\_quantile(0.99, sum(rate(http\_request\_duration\_seconds\_bucket\[5m])) by (le, path))

2\) Общие события приложения

app\_start\_total{mode} — запусков приложения.



alerts\_sent\_total{ok} — попыток отправить алерт (ok="1"/"0").



rate\_limit\_exceeded\_total{fn|operation} — срабатывания RL-декоратора.



3\) Брокер и сеть

broker\_requests\_total{exchange,method,code} — вызовы ccxt/бумажного брокера.



latency\_broker\_seconds — гистограмма сетевых вызовов брокера.



Примеры



promql

Копировать

Редактировать

sum by (method,code) (rate(broker\_requests\_total\[5m]))

histogram\_quantile(0.99, sum(rate(latency\_broker\_seconds\_bucket\[5m])) by (le))

4\) Decision/Order/Flow latency

latency\_build\_seconds — подготовка фич/индикаторов.



latency\_decide\_seconds — принятие решения.



latency\_order\_seconds — размещение ордера.



Пример p99



promql

Копировать

Редактировать

histogram\_quantile(0.99, sum(rate(latency\_decide\_seconds\_bucket\[15m])) by (le))

5\) Decision scores

decision\_score\_histogram — базовый score \[0..1].



decision\_score\_ctx\_histogram — контекстный вклад (перевод -1..+1 → \[0..1]).



decision\_score\_blended\_histogram — смешанный score (учитывает контекст, если включён).



6\) Risk

risk\_pass\_total — проход проверок риска.



risk\_block\_total{reason} — блокировки (причины: time\_sync\_\*, hours\_\*, spread\_\*, drawdown\_\*, seq\_losses\_\*, exposure\_\*).



Пример



promql

Копировать

Редактировать

topk(5, increase(risk\_block\_total\[1h]))  # какие причины чаще всего блокируют

7\) Очередь событий (Event Bus)

bus\_enqueued\_total{type,strategy} — положили в очередь.



bus\_dropped\_total{type,strategy} — дропнули (backpressure).



bus\_delivered\_total{type,handlers} — доставлено обработчикам.



bus\_dlq\_total{type} — в DLQ.



Сводка DLQ также отражается в events\_dead\_letter\_total (см. Ниже).



8\) SQLite

Снимок в /metrics:



sqlite\_page\_size\_bytes



sqlite\_page\_count



sqlite\_freelist\_pages



sqlite\_fragmentation\_percent



sqlite\_file\_size\_bytes



Примеры



promql

Копировать

Редактировать

avg(sqlite\_fragmentation\_percent)

max(sqlite\_file\_size\_bytes)

9\) Budgets (p99) и флаги превышения

performance\_budget\_exceeded{type,key} — 1/0, если p99 выше порога (ms).



performance\_budget\_exceeded\_any — 1, если превышено что-то из decision/order/flow.



Пороги задаются через ENV:



nginx

Копировать

Редактировать

PERF\_BUDGET\_DECISION\_P99\_MS

PERF\_BUDGET\_ORDER\_P99\_MS

PERF\_BUDGET\_FLOW\_P99\_MS

10\) Dead Letters (DLQ)

events\_dead\_letter\_total — текущее значение DLQ (gauge), экспортируется в /metrics.



11\) Circuit Breaker (экспорт в /metrics)

В нашем экспорте добавлены серии:



breaker\_state{key} — 0=closed, 1=half-open, 2=open



breaker\_calls\_total{key}, breaker\_errors\_total{key}, breaker\_openings\_total{key} — счётчики по ключам



breaker\_last\_error\_flag{key} — 1, если недавно было исключение



Пример



promql

Копировать

Редактировать

avg by (key) (breaker\_state)

increase(breaker\_openings\_total\[1h])

Практика: дашборд «за 10 минут»

Traffic



sum by (code) (rate(http\_requests\_total\[5m]))



Latency p99



histogram\_quantile(0.99, sum(rate(http\_request\_duration\_seconds\_bucket\[5m])) by (le, path))



histogram\_quantile(0.99, sum(rate(latency\_decide\_seconds\_bucket\[5m])) by (le))



histogram\_quantile(0.99, sum(rate(latency\_order\_seconds\_bucket\[5m])) by (le))



Risk blocks



topk(5, increase(risk\_block\_total\[1h])) by (reason)



Bus / DLQ



sum(increase(bus\_dropped\_total\[15m])) by (type,strategy)



events\_dead\_letter\_total



SQLite



sqlite\_fragmentation\_percent



Breaker



avg by (key) (breaker\_state)



increase(breaker\_openings\_total\[1h])



Как добавить новую метрику (рекомендуемый паттерн)

python

Копировать

Редактировать

from crypto\_ai\_bot.utils import metrics



\# counter

metrics.inc("orders\_total", {"side": "buy"})



\# gauge

metrics.gauge("positions\_open", 2)



\# histogram

with metrics.timer() as t:

&nbsp;   do\_work()

metrics.observe\_histogram("latency\_do\_work\_seconds", t.elapsed)

Важно: держи лейблы минимальными и предсказуемыми.



swift

Копировать

Редактировать



---



\# 🧹 Финальная зачистка



Мы уже удалили Docker-артефакты. Ещё два типа «мусора», которые часто всплывали:



1\) \*\*Устаревшие/пустые файлы, которые дублируют новую реализацию Market Context\*\*

&nbsp;  - `src/crypto\_ai\_bot/market\_context/indicators/btc\_dominance.py`

&nbsp;  - `src/crypto\_ai\_bot/market\_context/indicators/dxy\_index.py`

&nbsp;  - `src/crypto\_ai\_bot/market\_context/indicators/fear\_greed.py`



&nbsp;  > Вместо них используется `market\_context/providers.py` и `market\_context/snapshot.py`. Если эти файлы есть и не несут кода — \*\*удаляем\*\*.



2\) \*\*Инструменты, которые не используются\*\*

&nbsp;  - `src/crypto\_ai\_bot/utils/charts.py` — если реально не подключён нигде.



\### Команды (если файлы существуют)

```bash

git rm -f \\

&nbsp; src/crypto\_ai\_bot/market\_context/indicators/btc\_dominance.py \\

&nbsp; src/crypto\_ai\_bot/market\_context/indicators/dxy\_index.py \\

&nbsp; src/crypto\_ai\_bot/market\_context/indicators/fear\_greed.py \\

&nbsp; src/crypto\_ai\_bot/utils/charts.py || true



git commit -m "chore: remove obsolete empty indicators and unused charts module"

Пустые \_\_init\_\_.py НЕ трогаем — они нужны для импорта.



🔎 Обновлённая проверка архитектуры (необязательно, если уже есть)

Если хочешь, можно заменить наш аудит-скрипт более строгой версией: он подчёркивает не только пустые, но и «почти пустые» файлы (≤3 «содержательных» строк).



bash

Копировать

Редактировать

\# scripts/check\_architecture.sh

\#!/usr/bin/env bash

set -euo pipefail



ROOT="$(cd "$(dirname "${BASH\_SOURCE\[0]}")/.." \&\& pwd)"

cd "$ROOT"



echo "== Architecture sanity check =="



\# 1) Пустые или почти пустые (кроме \_\_init\_\_.py)

echo "-- Empty / nearly-empty python files:"

NEAR\_EMPTY=$( \\

&nbsp; find src -type f -name "\*.py" ! -name "\_\_init\_\_.py" \\

&nbsp; -exec awk '

&nbsp;   BEGIN{nonblank=0}

&nbsp;   {

&nbsp;     line=$0

&nbsp;     # считаем «содержательной» строкой то, что не только пробелы/комменты

&nbsp;     if (line !~ /^\[\[:space:]]\*$/ \&\& line !~ /^\[\[:space:]]\*#/) nonblank++

&nbsp;   }

&nbsp;   END{

&nbsp;     if (nonblank <= 3) print FILENAME

&nbsp;   }' {} + \\

)

if \[\[ -n "${NEAR\_EMPTY:-}" ]]; then

&nbsp; echo "$NEAR\_EMPTY"

&nbsp; echo "✗ Found empty/nearly-empty stubs ↑"

else

&nbsp; echo "✓ none"

fi



\# 2) Критичные файлы присутствуют

echo "-- Critical files presence:"

CRIT=0

for p in \\

&nbsp; "src/crypto\_ai\_bot/app/server.py" \\

&nbsp; "src/crypto\_ai\_bot/utils/metrics.py" \\

&nbsp; "src/crypto\_ai\_bot/utils/logging.py" \\

&nbsp; "src/crypto\_ai\_bot/utils/rate\_limit.py" \\

&nbsp; "src/crypto\_ai\_bot/core/events/async\_bus.py" \\

&nbsp; "src/crypto\_ai\_bot/core/events/factory.py" \\

&nbsp; "src/crypto\_ai\_bot/core/use\_cases/evaluate.py" \\

&nbsp; "src/crypto\_ai\_bot/core/use\_cases/place\_order.py" \\

&nbsp; "src/crypto\_ai\_bot/core/use\_cases/eval\_and\_execute.py" \\

&nbsp; "src/crypto\_ai\_bot/core/brokers/ccxt\_exchange.py" \\

&nbsp; "src/crypto\_ai\_bot/core/storage/sqlite\_adapter.py"

do

&nbsp; if \[\[ -f "$p" ]]; then

&nbsp;   echo "✓ $p"

&nbsp; else

&nbsp;   echo "✗ missing: $p"; CRIT=1

&nbsp; fi

done



echo "-- Tips:"

echo "• Run 'uvicorn crypto\_ai\_bot.app.server:app --reload' and check /health, /status/extended, /metrics, /context."

echo "• Use '.env.example' as canonical env template."

exit $CRIT

Добавь цель в Makefile (если ещё не добавлял):



makefile

Копировать

Редактировать

check:

&nbsp;	@bash scripts/check\_architecture.sh || true

