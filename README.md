ФИНАЛЬНЫЙ README.md (идеальная целевая версия)

Включает: строгие границы слоёв и инварианты, контроль зависимостей, безопасность по умолчанию, многоуровневую Telegram-интеграцию, фиксированную архитектуру сигналов и веса/пороговые правила, бизнес-конвейер, PnL(FIFO)/fee, наблюдаемость, API, конфигурацию и структуру с краткими функциями файлов (основных). Факты и настройки берутся из текущих документов и структуры. 
 
 

Crypto-AI-Bot (Gate.io via CCXT) — Clean Architecture, paper & live

Бизнес-конвейер (единый для paper/live):
evaluate → risk → execute_trade → protective_exits → reconcile (+settlement) → watchdog. 

Ключевые гарантии

Чистая архитектура: строгое разделение app / core(application→domain→infrastructure) / utils, с контрактами import-linter. 

PnL FIFO + fee_quote: /pnl/today считает реализованный PnL по FIFO, учитывая частичные исполнения и комиссии. 

Risk by default: LossStreak, MaxDrawdown, дневные бюджеты, капы на 5м/час/день, cooldown, spread-cap, daily loss. Всё проходит через один «воротный» RiskManager. 

Idempotency: уникальные client_order_id + ключи в БД, окно IDEMPOTENCY_BUCKET_MS, TTL. 

Наблюдаемость: /metrics, /health, /ready, алерты в Telegram, webhook Alertmanager. (Prometheus/Alertmanager/Grafana — на Railway, конфиги вне репо). 

Архитектура слоёв и жёсткие границы

Слои:

app/ — HTTP/CLI/Telegram, DI-композиция зависимостей, подписчики (без бизнес-логики).

core/application/ — оркестрация сценариев (orchestrator, use-cases, reconciliation, monitoring, regime gating), работает через порты.

core/domain/ — чистая бизнес-модель: стратегии, сигналы, риск-правила, макро-типажи; без IO и внешних SDK.

core/infrastructure/ — адаптеры: брокеры (Paper/CCXT), storage (SQLite+миграции, репозитории), events (InMem/Redis), market_data, safety (DMS/locks), settings/schema.

utils/ — Decimal/metrics/retry/trace/pnl/symbols/…

Инварианты импортов (контроль линтером):

domain ↛ infrastructure|app запрещено.

application ↛ infrastructure|app запрещено (только через ports.py).

app может зависеть от application и инстанциировать адаптеры infrastructure.

Все интеграции — только внедрением через compose.py.
(Контракты import-linter + требования к PR — см. ниже) 

Инварианты (выполняются всегда)

Деньги/объёмы = Decimal. Все преобразования — в utils/decimal.py. 

Idempotency для критичных операций (заказ, settle, reconcile). 

Signals/Strategies возвращают чистые DTO: тип, score, confidence, без побочных эффектов. 

Risk-rules — отдельные объекты в core/domain/risk/rules/*, агрегирует RiskManager. 

IO-вызовы обёрнуты таймаутами/ретраями/метриками; логирование структурированное. 

Ни одного прямого CCXT-вызова вне инфраструктурного адаптера. 

Одна реализация логики (никаких дубликатов путей исполнения). PR не мержим, если дублирует. 

Безопасность по умолчанию

Live-режим только с DeadMansSwitch и InstanceLock. 

Жёсткие дефолты Risk включены (loss streak, max DD, budgets, cooldown, spread cap). 

Идемпотентность (БД+индексы), уникальные client_order_id. 

Telegram-алерты по ERROR (вкл. LOG_TG_ERRORS=1). 

Секреты — только через ENV, без хранения в репозитории.

Многоуровневая Telegram-интеграция

Операторский бот (app/adapters/telegram_bot.py) — команды статуса/паузы/рестарта, запросы PnL/перф.

Алерты трейдинга (app/subscribers/telegram_alerts.py) — trade.completed/failed/settled/blocked, budget.exceeded, safety.dms.*, reconcile.*, dlq.*. Топики объявлены на уровне application. 

Алерты SRE — webhook /alertmanager/webhook из Railway Prometheus → выделенный чат. ENV раздельные: TELEGRAM_CHAT_ID (операционный), TELEGRAM_ALERTS_CHAT_ID (SRE). 

Архитектура сигналов (фиксированная)
Multi-Timeframe (MTF)

15m (вес 0.40) — основной вход,

1h (0.25) — подтверждение тренда,

4h (0.20) — среднесрочный тренд,

1d (0.10) — дневной bias,

1w (0.05) — долгосрочный контекст.
Веса — дефолт в settings_schema.py, меняются только через код-ревью, не ENV. 

Fusion

Технический скор (RSI/MACD/EMA/BB/ATR, свечные паттерны) — 65%,

ИИ-скор (ONNX/логистическая) — 35%,

Макро-множитель: 0.90…1.10 на пороги/долю позиции. 
 

Пороговые профили после macro:

bull: ind ≥ 60 и ai ≥ 65,

neutral: ind ≥ 65 и ai ≥ 65,

bear: ind ≥ 70 и ai ≥ 70;
если ai_score=None — требуем ind ≥ (порог + 5), и зона воздержания AI 45..55. 

Risk Management (одни ворота)

RiskManager.check() агрегирует: LossStreak, MaxDrawdown, дневной убыток/бюджет, частотные капы (5m/час/день), cooldown, spread-cap, антикорреляцию крипто-мажоров. Нарушение → trade.blocked. 
 

Execute Trade (единственный путь)

Идемпотентный client_order_id (например, sha1(symbol|side|slot)), выравнивание под precision/step, проверки minQty/minNotional, учёт max_slippage. Никаких альтернативных «place_order» путей. 

Protective Exits

ATR-модель: TP1=+1×ATR (50% + перенос SL в б/у), TP2=+2×ATR (остаток), SL=−1.5×ATR; либо фиксированные TP/SL/Trailing по настройкам. 

Reconcile & Settlement

Сверка позиций/балансов/ордеров, доведение частичных исполнений до финала (trade.settled/failed_settlement). Есть таблица orders и миграции V0012__orders_table.sql. 

PnL FIFO и комиссии

FIFO в utils/pnl.py, /pnl/today считает реализованный PnL за «сегодня», оборот и количество сделок, учитывая fee_quote и частичные исполнения. 

События и шина

In-Memory по умолчанию; для надёжности — EVENT_BUS_URL=redis://.... Темы: trade.completed/failed/settled/blocked, budget.exceeded, orchestrator.auto_*, safety.dms.*, reconcile.*, dlq.* — определены в core/application/events_topics.py. 

Конфигурация (ENV, проверяется schema)

Примеры:

Режимы/интеграции: MODE=paper|live, EXCHANGE=gateio, API_KEY/SECRET, EVENT_BUS_URL, TELEGRAM_*. 

Символы/интервалы: SYMBOLS=BTC/USDT,ETH/USDT, EVAL_INTERVAL_SEC, EXITS_INTERVAL_SEC, RECONCILE_INTERVAL_SEC.

Стратегии: STRATEGY_SET, STRATEGY_MODE=first|vote|weighted, POSITION_SIZER=.... 

Риски: RISK_MAX_SPREAD_PCT, RISK_MAX_DRAWDOWN_PCT, RISK_LOSS_STREAK_LIMIT, RISK_DAILY_LOSS_LIMIT_QUOTE, RISK_MAX_ORDERS_PER_HOUR, IDEMPOTENCY_BUCKET_MS. 

Прежние SAFETY_* поддерживаются как алиасы (обратная совместимость). 

REST-API

GET /health — проверка DB/Bus/Broker + публикация health.report.

GET /ready — готовность.

GET /metrics — Prometheus.

GET /pnl/today?symbol=... — PnL(реализ.)/оборот/сделки.

GET /orchestrator/status?symbol=..., POST /orchestrator/{start|stop|pause|resume}?symbol=....

POST /alertmanager/webhook — входящих алертов. 

Структура и краткий функционал файлов (главные узлы)

app/server.py — FastAPI: /health, /ready, /metrics, /pnl, /orchestrator/*, /alertmanager/webhook. 

app/compose.py — DI: Settings/Storage/EventBus/Broker/Orchestrator/Telegram.

app/adapters/telegram_bot.py — команды оператора (статус/пауза/перезапуск, PnL).

app/subscribers/telegram_alerts.py — подписчик на торговые/сервисные события.

core/application/orchestrator.py — главный цикл; monitoring/*, reconciliation/*. 

core/application/use_cases/eval_and_execute.py — оценка сигналов + вызов risk + execute_trade. 

core/application/use_cases/execute_trade.py — единственный путь постановки ордеров. 

core/application/use_cases/partial_fills.py — settle частичных исполнений. 

core/application/events_topics.py — единый словарь тем (теперь на слое application). 

core/domain/strategies/* — EMA/RSI/BB/ATR, position sizing, manager (first/vote/weighted). 

core/domain/signals/* — MTF, fusion, ai_scoring, policy, macro-bias. 

core/domain/risk/manager.py + risk/rules/* — все лимиты/правила в одном месте. 

core/infrastructure/brokers/* — CCXT-адаптер Gate.io + paper, фабрика. 

core/infrastructure/storage/sqlite_adapter.py + migrations/* + repositories/* — БД, миграции (в т.ч. V0012__orders_table.sql). 

utils/pnl.py — FIFO-PnL; utils/metrics.py — Prometheus; utils/decimal.py — Decimal. 

Контроль слоёв (import-linter) и проверки PR

Нельзя мержить PR, если красный import-linter/mypy/pytest, нет миграций при изменении схемы, не обновлён README/.env.example, добавлен «мёртвый код», дублируется логика. 

В каждом PR ответь на вопросы: «куда ложится в архитектуре? есть порт? какие инварианты затрагиваю? где мониторится? нет ли дублей?» (см. чек-лист). 

Запуск
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000
# CLI:
cab-smoke | cab-health-monitor | cab-perf | cab-reconcile


Деплой и наблюдаемость

Railway: web (FastAPI), worker (health/оркестрация), Redis (шина), Prometheus/Alertmanager/Grafana — вне репозитория, webhook в /alertmanager/webhook, алерты в Telegram. 

Готовность к production

Блокеры сняты при: единый execute_trade, DI-regime, settle partial fills, инварианты ENV и линтер-контракты — всё отмечено в дорожной карте. (Сейчас по коду это достижимо короткими правками.)