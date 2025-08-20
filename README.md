markdown# crypto-ai-bot — Production-Ready Trading System

🚀 **Enterprise-grade** крипто-торговая система на **FastAPI** с полной интеграцией **Gate.io**, protective exits, reconciliation и production monitoring.

> **Статус:** Production-Ready | **Обновлено:** 2025-08-19 | **Аудит:** ✅ Пройден

---

## 🎯 **КЛЮЧЕВЫЕ ОСОБЕННОСТИ**

### **💎 Production Features**
- ✅ **Full Order Reconciliation** — автосверка с биржей каждые 60 сек
- ✅ **Protective Exits** — автоматический SL/TP с мониторингом  
- ✅ **Circuit Breakers** — защита от API сбоев с auto-recovery
- ✅ **Graceful Shutdown** — корректное завершение всех операций
- ✅ **Comprehensive Monitoring** — 50+ метрик для production

### **🛡️ Risk Management**
- ✅ **Position Limits** — MAX_POSITIONS enforcement
- ✅ **Drawdown Protection** — автостоп при превышении лимитов
- ✅ **Sequential Loss Limits** — защита от серий убытков
- ✅ **Time-based Trading** — торговые часы и временные ограничения

### **🔧 Gate.io Integration**
- ✅ **Native Symbol Format** — BTC_USDT для Gate.io
- ✅ **Precision Handling** — минимальные лоты и точность
- ✅ **Rate Limit Management** — 300 calls/10sec соблюдение
- ✅ **Status Mapping** — полная обработка Gate.io статусов

---

## 🏗️ **АРХИТЕКТУРА**
crypto-ai-bot/
├─ requirements.txt
├─ .env.example
├─ ops/prometheus/          # 🔥 Production alerts
│  └─ alerts.yml           # 20+ production-ready rules
├─ scripts/
│  ├─ reconciler.py        # 🔥 Order reconciliation service
│  ├─ protective_exits.py  # 🔥 SL/TP execution service
│  └─ health_monitor.py    # 🔥 System health monitoring
└─ src/crypto_ai_bot/
├─ app/
│  ├─ server.py         # FastAPI + comprehensive health checks
│  ├─ compose.py        # 🔥 Production DI container
│  └─ adapters/
│     └─ telegram.py    # Full command set: /eval, /why
├─ core/
│  ├─ settings.py       # 🔥 Production configuration
│  ├─ orchestrator.py   # 🔥 Full lifecycle management
│  ├─ use_cases/        # evaluate / eval_and_execute / place_order
│  ├─ signals/
│  │  ├─ _build.py
│  │  ├─ _fusion.py     # 🔥 Signal fusion logic
│  │  └─ policy.py
│  ├─ brokers/
│  │  ├─ base.py
│  │  ├─ ccxt_impl.py   # 🔥 Renamed from ccxt_exchange.py
│  │  └─ gateio_config.py # 🔥 Gate.io specific configuration
│  ├─ risk/
│  │  ├─ manager.py     # 🔥 Enhanced risk rules
│  │  └─ protective_exits.py # 🔥 SL/TP execution engine
│  └─ storage/
│     ├─ reconciler.py  # 🔥 Order reconciliation
│     └─ repositories/  # trades, positions, exits, audit
└─ utils/
├─ retry.py          # 🔥 Centralized retry logic
├─ circuit_breaker.py # 🔥 Enhanced with auto-recovery
└─ graceful_shutdown.py # 🔥 Production shutdown handler

---

## ⚡ **БЫСТРЫЙ СТАРТ**

### **1. Установка**
```bash
# Development setup
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows

pip install -r requirements.txt
# pip install -e .[dev]  # С development tools
2. Конфигурация
bashcp .env.example .env
# Настройте .env файл с вашими API ключами
3. Запуск Development
bashexport PYTHONPATH=src
uvicorn crypto_ai_bot.app.server:app --reload --host 0.0.0.0 --port 8000
4. Проверка работоспособности
bash# Health check
curl http://localhost:8000/health

# Metrics
curl http://localhost:8000/metrics

# Telegram test (если настроен)
# Отправьте /status в Telegram бот
🚀 PRODUCTION DEPLOYMENT
Railway.app (Рекомендуется)

bash
Копировать
Редактировать
# 1. Deploy
railway login
railway init
railway up

# 2. Environment Variables  
railway variables set MODE=live
railway variables set ENABLE_TRADING=true
railway variables set DB_PATH=/data/bot.sqlite
railway variables set EXCHANGE=gateio
railway variables set SYMBOL="BTC/USDT"
railway variables set TIMEFRAME=15m

# 3. Volume для данных
railway volume create --name trading-data --mount /data

# 4. Мониторинг
railway logs --follow
Docker (Alternative)

dockerfile
Копировать
Редактировать
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
ENV PYTHONPATH=src
EXPOSE 8000
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "crypto_ai_bot.app.server:app"]
📊 MONITORING & OBSERVABILITY
Ключевые метрики

yaml
Копировать
Редактировать
# Trading Metrics
- orders_success_total / orders_fail_total
- position_sync_drift_seconds  
- protective_exits_triggered_total
- slippage_actual_bps vs slippage_expected_bps
- pnl_calculated vs pnl_exchange_difference

# System Metrics  
- reconciliation_errors_total
- circuit_breaker_state{name,state}
- graceful_shutdown_duration_seconds
- risk_blocks_total{rule}

# Performance Metrics
- latency_decision_seconds (P95/P99)
- latency_order_execution_seconds (P95/P99) 
- performance_budget_exceeded_total{component}
Alerts (Prometheus)

yaml
Копировать
Редактировать
# Critical Alerts
- TradingSystemDown (1min)
- OrderReconciliationFailed (2min)  
- ProtectiveExitStuck (5min)
- DrawdownLimitExceeded (1min)

# Warning Alerts
- HighOrderLatency (5min)
- CircuitBreakerOpen (1min)
- PositionSyncLost (10min)
🎮 TELEGRAM COMMANDS
Основные команды

/help — список всех команд

/status — состояние системы и позиций

/health — детальная диагностика системы

Trading операции

/eval [SYMBOL] [TF] [LIMIT] — 🔥 расчет сигнала без исполнения

/why [SYMBOL] [TF] [LIMIT] — 🔥 объяснение торгового решения

/profit [SYMBOL] — PnL статистика и график

/positions [SYMBOL] — открытые позиции

Мониторинг

/test — smoke test всех систем

/metrics — ключевые метрики системы

/exits — статус protective exits

⚙️ КОНФИГУРАЦИЯ
Основные параметры

env
Копировать
Редактировать
# === TRADING SETUP ===
MODE=live                    # paper/live
ENABLE_TRADING=true         # Главный выключатель
SYMBOL=BTC/USDT            # Торгуемая пара
TIMEFRAME=15m              # Таймфрейм

# === GATE.IO SETUP ===  
EXCHANGE=gateio
CCXT_ENABLE_RATE_LIMIT=true
ORDERS_RPS=10
ACCOUNT_RPS=30

# === RISK MANAGEMENT ===
MAX_POSITIONS=3                 # 🔥 Максимум позиций
RISK_MAX_LOSSES=3              # 🔥 Лимит подряд идущих убытков
RISK_MAX_DRAWDOWN_PCT=10.0     # 🔥 Максимальная просадка
RISK_HOURS_UTC=08:00-22:00     # 🔥 Торговые часы
SLIPPAGE_BPS=20.0              # 🔥 Допустимое проскальзывание (bps)
MAX_SPREAD_BPS=50.0            # 🔥 Макс. спред (bps)

# === RECONCILIATION ===
IDEMPOTENCY_TTL_SEC=60      # 🔥 TTL идемпотентности (анти-дубли заявок)
MARKET_DATA_RPS=60          # 🔥 Частота рыночных запросов (RPS)

# === PERFORMANCE ===
CB_FAIL_THRESHOLD=5                # 🔥 Ошибок до открытия (circuit breaker)
CB_OPEN_TIMEOUT_SEC=30.0           # 🔥 Таймаут open-состояния
CB_WINDOW_SEC=60.0                 # 🔥 Окно подсчёта ошибок

# Production секреты
# === SECURITY ===
TELEGRAM_BOT_TOKEN=bot123:secret
TELEGRAM_BOT_SECRET=webhook_secret
TELEGRAM_ALERT_CHAT_ID=-100123456  # 🔥 Для alerts

# === STORAGE ===
DB_PATH=/data/bot.sqlite          # Production path
DB_JOURNAL_MODE_WAL=true          # 🔥 WAL для SQLite

# === MONITORING ===
LOG_LEVEL=INFO                    # DEBUG/INFO/WARNING/ERROR
🧪 TESTING
Test suites

bash
Копировать
Редактировать
# Unit tests
pytest tests/unit/ -v

# Integration tests  
pytest tests/integration/ -v --timeout=30

# Architecture compliance
./scripts/check_architecture.sh

# Performance tests
pytest tests/performance/ -v -m "not slow"

# Full test suite
pytest -v --cov=crypto_ai_bot --cov-report=html
Pre-deployment checklist

bash
Копировать
Редактировать
# 🔥 КРИТИЧНО перед production
□ ./scripts/smoke_test.sh passes  
□ All /health endpoints return healthy
□ Reconciliation service connects to Gate.io
□ Protective exits can be created and triggered
□ Rate limits are properly configured
□ Graceful shutdown works within 30 seconds
□ All alerts fire correctly in test environment
perl
Копировать
Редактировать

Основано на переменных и дефолтах из актуального `core/settings.py` (MODE, SYMBOL, TIMEFRAME, EXCHANGE, risk-параметры, RPS и circuit breaker, БД и Telegram и пр.). :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1} :contentReference[oaicite:2]{index=2}

Для сравнения, исходные места `README.md`, которые были затронуты (замена GATEIO_API_KEY/SECRET, POSITION_SIZE_USD, STOP/TAKE_PROFIT, RECONCILE_*, PERF_BUDGET_*, TELEGRAM_WEBHOOK_SECRET, DB_BACKUP_INTERVAL_HOURS, SENTRY_DSN), см. строки 107–113 и 183–223 оригинала. :contentReference[oaicite:3]{index=3} :contentReference[oaicite:4]{index=4}

Если хочешь, сгенерирую такой же **минимальный diff** к `.env.example` строго в его исходном формате — пришли файл или дай доступ.
::contentReference[oaicite:5]{index=5}