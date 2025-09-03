crypto-ai-bot

Автотрейдинг криптовалют (Gate.io через CCXT) с единой логикой для paper и live:
strategies → regime filter → risk/limits → execute_trade → protective_exits → reconcile → watchdog → settlement.

Чистая архитектура: строгие границы app / core (application → domain → infrastructure) / utils и контроль импортов.

Безопасность по умолчанию: идемпотентность, лимиты риска, защитные выходы, DMS/InstanceLock, throttle брокера.

Наблюдаемость: Prometheus-метрики, health/ready, Telegram (алерты и команды), интеграция Alertmanager.

Восстановление: сверки и доведение частичных исполнений (settlement) с записью в БД.

📦 Установка и запуск
1) Окружение
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate

pip install -U pip wheel
pip install -e .

2) Конфигурация

Скопируйте .env.example → .env и задайте переменные.
Секреты поддерживаются в форматах: NAME_FILE (путь к файлу), NAME_B64 (base64), или единый SECRETS_FILE (JSON).

3) API (локально)
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000

4) CLI (сервисные команды)
# Быстрый smoke-чек
cab-smoke

# БД: бэкап/ротация/вакуум/интегрити/список
cab-maintenance backup
cab-maintenance rotate --days 30
cab-maintenance vacuum
cab-maintenance integrity
cab-maintenance list

# Сверки (балансы/позиции)
cab-reconcile

# Мониторинг health (когда API запущен)
cab-health-monitor --oneshot --url http://127.0.0.1:8000/health

# Отчёт по сделкам/PNL (FIFO) за сегодня
cab-perf

🔌 HTTP-эндпоинты

GET /health — текущее состояние (БД/шина/биржа).

GET /ready — готовность (200/503).

GET /metrics — Prometheus.

GET /orchestrator/status?symbol=BTC/USDT — состояние оркестратора.

POST /orchestrator/(start|stop|pause|resume)?symbol=... — управление (Bearer API_TOKEN).

GET /pnl/today?symbol=... — PnL за сегодня (FIFO) + сводка.

🤖 Telegram (многоуровневая интеграция)

Разделение обязанностей (без дублей):

app/adapters/telegram.py — publisher: только исходящие алерты (ретраи, HTML, дедуп/антишторм).

app/adapters/telegram_bot.py — operator bot: только входящие команды (whitelist/roles).

app/subscribers/telegram_alerts.py — подписчик EventBus → Telegram (в т.ч. Alertmanager вебхуки).

Команды бота (основные):
/status, /today, /pnl, /position, /balance, /limits, /pause, /resume, /stop, /health.

Если TELEGRAM_* не заданы — интеграции работают в no-op (безопасно).

🧱 Архитектура и правила слоёв
Слои и зависимости

app/ — HTTP API (FastAPI), DI/compose, Telegram адаптеры/подписчики.
Может импортировать: core.application, core.infrastructure, utils.

core/application/ — оркестрация, use-cases, protective exits, reconciliation, monitoring, реестр тем событий.
Может импортировать: core.domain, utils. Не может: app, core.infrastructure.

core/domain/ — чистые бизнес-правила (risk, стратегии, сигналы, режимы).
Может импортировать: utils. Не может: app, core.application, core.infrastructure.

core/infrastructure/ — брокеры (CCXT/Paper), шина (Redis/in-mem), storage (SQLite+миграции), safety (DMS/lock), settings.
Может импортировать: utils. Не может: app, core.application, core.domain.

utils/ — общие утилиты (Decimal, логи, метрики, retry, http, pnl, trace, symbols).

Контроль слоёв: importlinter.ini (CI падает при нарушении).

Инварианты (валидация при старте)

MTF weights: 15m=0.40, 1h=0.25, 4h=0.20, 1d=0.10, 1w=0.05 (сумма = 1.0).

Fusion weights: technical=0.65, ai=0.35 (сумма = 1.0).

Settings читаются только через core/infrastructure/settings.py.

Деньги — только Decimal (utils.decimal.dec()).

Асинхронщина без time.sleep (только asyncio.sleep).

Темы событий — только константы core/application/events_topics.py (никаких «магических строк»).

🗂️ Актуальная файловая структура

Важно: папка ops/prometheus/ (Prometheus/Alertmanager/Grafana) уже развернута на Railway и из репозитория исключена — мы оставили только обработчик вебхука Alertmanager в приложении. Это снижает шум в репо и поддерживает «инфру как внешний сервис».

crypto-ai-bot/
├─ README.md
├─ pyproject.toml
├─ requirements*.txt
├─ Makefile
├─ Procfile
├─ .gitignore
├─ pytest.ini
├─ importlinter.ini
├─ scripts/
│  ├─ backup_db.py
│  ├─ rotate_backups.py
│  ├─ integrity_check.py
│  ├─ run_server.sh
│  └─ run_server.ps1
└─ src/crypto_ai_bot/
   ├─ app/
   │  ├─ server.py
   │  ├─ compose.py
   │  ├─ logging_bootstrap.py
   │  ├─ adapters/
   │  │  ├─ telegram.py          # publisher
   │  │  └─ telegram_bot.py      # commands
   │  └─ subscribers/
   │     └─ telegram_alerts.py   # EventBus→Telegram (+ Alertmanager)
   ├─ cli/
   │  ├─ smoke.py
   │  ├─ maintenance.py
   │  ├─ reconcile.py
   │  ├─ performance.py
   │  └─ health_monitor.py
   ├─ core/
   │  ├─ application/
   │  │  ├─ orchestrator.py
   │  │  ├─ ports.py
   │  │  ├─ events_topics.py     # ← единый реестр событий
   │  │  ├─ protective_exits.py
   │  │  ├─ use_cases/
   │  │  │  ├─ eval_and_execute.py
   │  │  │  ├─ execute_trade.py  # ← единственная точка размещения ордеров
   │  │  │  └─ partial_fills.py  # settlement/доведение частичных
   │  │  ├─ reconciliation/
   │  │  │  ├─ orders.py
   │  │  │  ├─ positions.py
   │  │  │  └─ balances.py
   │  │  ├─ regime/
   │  │  │  └─ gated_broker.py
   │  │  └─ monitoring/
   │  │     └─ health_checker.py
   │  ├─ domain/
   │  │  ├─ risk/
   │  │  │  ├─ manager.py
   │  │  │  └─ rules/
   │  │  │     ├─ loss_streak.py
   │  │  │     ├─ max_drawdown.py
   │  │  │     ├─ max_orders_5m.py
   │  │  │     ├─ max_turnover_5m.py
   │  │  │     ├─ cooldown.py
   │  │  │     ├─ daily_loss.py
   │  │  │     ├─ spread_cap.py
   │  │  │     └─ correlation_manager.py
   │  │  ├─ strategies/ ...       # (EMA/RSI/Bollinger/ATR/…)
   │  │  ├─ signals/
   │  │  │  ├─ timeframes.py
   │  │  │  ├─ fusion.py
   │  │  │  ├─ ai_model.py
   │  │  │  ├─ ai_scoring.py
   │  │  │  └─ feature_pipeline.py
   │  │  └─ macro/
   │  │     ├─ regime_detector.py
   │  │     └─ types.py
   │  └─ infrastructure/
   │     ├─ settings.py
   │     ├─ settings_schema.py
   │     ├─ brokers/
   │     │  ├─ base.py
   │     │  ├─ factory.py
   │     │  ├─ ccxt_adapter.py
   │     │  ├─ live.py
   │     │  └─ paper.py
   │     ├─ events/
   │     │  ├─ bus.py
   │     │  ├─ bus_adapter.py
   │     │  └─ redis_bus.py
   │     ├─ safety/
   │     │  ├─ dead_mans_switch.py
   │     │  └─ instance_lock.py
   │     ├─ storage/
   │     │  ├─ facade.py
   │     │  ├─ sqlite_adapter.py
   │     │  ├─ backup.py
   │     │  └─ migrations/
   │     │     ├─ runner.py
   │     │     ├─ V0001__init.sql
   │     │     ├─ V0006__trades_indexes.sql
   │     │     ├─ V0007__idempotency_unique_and_ts.sql
   │     │     ├─ V0008__positions_idx.sql
   │     │     ├─ V0009__trades_unique_ids.sql
   │     │     ├─ V0010__audit_ts_idx.sql
   │     │     └─ V0012__orders_table.sql
   │     └─ macro/
   │        └─ sources/
   │           ├─ http_dxy.py
   │           ├─ http_btc_dominance.py
   │           └─ http_fomc.py
   └─ utils/
      ├─ decimal.py
      ├─ pnl.py
      ├─ metrics.py
      ├─ logging.py
      ├─ retry.py
      ├─ http_client.py
      ├─ symbols.py
      ├─ time.py
      └─ trace.py


Примечание: place_order.py исторически существовал как мостик — теперь вся постановка ордеров идёт через execute_trade.py. Если нет внешних импортов на place_order.py, файл можно убрать.

🔄 Торговый конвейер (сигнальный пайплайн)

Multi-Timeframe Analysis (signals/timeframes.py)
15m=40% · 1h=25% · 4h=20% · 1d=10% · 1w=5% (инвариант, фиксируется в settings_schema.py)

Signal Fusion (signals/fusion.py)
Technical=65% · AI=35% (инвариант)

Strategy Aggregation (strategies/strategy_manager.py)
first | vote | weighted

Regime Filtering (application/regime/gated_broker.py)
Источники: DXY, BTC dominance, FOMC. risk_off блокирует новые входы/сужает объём.

Risk Management (domain/risk/)
LossStreak, MaxDrawdown, MaxOrders5m, MaxTurnover5m, Cooldown, DailyLoss, SpreadCap, Anti-Correlation.

Execute (use_cases/execute_trade.py) — единая точка исполнения + идемпотентность.

Protective Exits (protective_exits.py) — hard/trailling стопы.

Reconcile (reconciliation/*) — позиции/балансы.

Watchdog (monitoring/health_checker.py) — health/DMS.

Settlement (use_cases/partial_fills.py) — доведение частично исполненных ордеров.

🛡️ Безопасность по умолчанию

Идемпотентность: client_order_id + idempotency-репозиторий (TTL).

Бюджеты: дневные лимиты количества ордеров и оборота (quote).

Анти-бёрст: лимиты на 5 минут (orders/turnover).

Cooldown: минимальный интервал между сделками.

SpreadCap: запрет сделок при завышенном спрэде.

DailyLoss: стоп по дневному реализованному убытку (quote).

Anti-Correlation: запрет одновременных позиций в высоко-коррелированных группах.

Throttle брокера: BROKER_RATE_RPS/BURST.

DMS: защищённая распродажа при зависаниях.

Секреты: только через *_FILE/*_B64/SECRETS_FILE.

⚙️ ENV (основные)
Торговля
MODE=paper|live
EXCHANGE=gateio
SYMBOLS=BTC/USDT,ETH/USDT
FIXED_AMOUNT=50
PRICE_FEED=fixed
FIXED_PRICE=100

MTF / Fusion (инварианты: сумма = 1.0)
MTF_W_M15=0.40
MTF_W_H1=0.25
MTF_W_H4=0.20
MTF_W_D1=0.10
MTF_W_W1=0.05

FUSION_W_TECHNICAL=0.65
FUSION_W_AI=0.35

Risk & Safety
RISK_COOLDOWN_SEC=60
RISK_MAX_SPREAD_PCT=0.30
RISK_MAX_SLIPPAGE_PCT=0.10
RISK_DAILY_LOSS_LIMIT_QUOTE=100

RISK_MAX_ORDERS_5M=0
RISK_MAX_TURNOVER_5M_QUOTE=0
SAFETY_MAX_ORDERS_PER_DAY=7
SAFETY_MAX_TURNOVER_QUOTE_PER_DAY=5000

Regime
REGIME_ENABLED=1
REGIME_DXY_URL=...
REGIME_BTC_DOM_URL=...
REGIME_FOMC_URL=...
REGIME_DXY_LIMIT_PCT=0.35
REGIME_BTC_DOM_LIMIT_PCT=0.60
REGIME_FOMC_BLOCK_HOURS=8

Telegram
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_ALERTS_CHAT_ID=...
TELEGRAM_BOT_COMMANDS_ENABLED=1
TELEGRAM_ALLOWED_USERS=123,456

Инфраструктура
EVENT_BUS_URL=redis://redis:6379/0   # пусто = in-memory
DB_PATH=./data/trader-gateio-BTCUSDT-paper.sqlite3
API_TOKEN=...           # для HTTP управления
API_KEY=...             # Gate.io live
API_SECRET=...

🧪 Тестирование и мониторинг

CLI: cab-smoke, cab-health-monitor, cab-perf, cab-reconcile.
Prometheus: /metrics + Alertmanager → Telegram (через app/subscribers/telegram_alerts.py).
Health/Ready: чёткие статусы для оркестратора и зависимостей.

🔎 Контроль качества (что проверяем регулярно)

Бизнес-цикл: цепочка evaluate → risk → execute_trade → protective_exits → reconcile → watchdog → settlement согласована.

PnL/FIFO/fees: верный учёт комиссий (fee_quote), консистентность /pnl/today.

Risk: LossStreak, MaxDrawdown, лимиты 5m/day — срабатывают и логируются.

Graceful shutdown: корректно закрываются orchestrator, EventBus, CCXT-клиент.

Интеграции: Gate.io (CCXT), Redis, SQLite, Alertmanager→Telegram, Telegram-бот.

Мультисимвольность: поддержка SYMBOLS во всех узлах (orchestrator/PnL/reconciler).

Наблюдаемость: метрики и health-чеки соответствуют описанию.

Prod-готовность: Railway манифест/сикреты/переменные, бэкапы БД и восстановление.

🚀 Деплой на Railway

Procfile:

web: uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port $PORT
worker: python -m crypto_ai_bot.cli.health_monitor --daemon


Интеграции: Railway (приложение), Redis (шина событий), Prometheus/Alertmanager/Grafana (внешние, вебхук в приложение), SQLite (WAL) + бэкапы/ротация.

Примечания по чистке артефактов

Когда все импорты переведены на execute_trade, файл-мостик place_order.py можно удалить.

Ранее хранившийся в репо ops/prometheus/ удалён, т.к. мониторинг развёрнут как внешний сервис на Railway (конфиги держим там).