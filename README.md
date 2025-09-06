# crypto-ai-bot

**Версия**: 1.0-beta (2025-01-10)

## Оглавление
- [Что это](#что-это)
- [Архитектурные ограничения](#архитектурные-ограничения-критично)
- [Основные характеристики](#основные-характеристики)
- [Архитектурные принципы](#архитектурные-принципы-обязательные)
- [Ключевые особенности](#ключевые-особенности)
- [Архитектура](#архитектура)
- [Структура файлов](#структура-файлов)
- [Стратегия торговли](#стратегия-торговли)
- [Конфигурация](#конфигурация)
- [Getting Started](#getting-started-быстрый-старт)
- [Запуск](#запуск)
- [Тестирование](#тестирование)
- [Мониторинг](#мониторинг)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap--todo)
- [Contributing Guidelines](#contributing-guidelines)
- [Performance](#performance)
- [Контакты](#контакты)

## Что это
Автоматизированный торговый бот для криптовалют с Clean Architecture.

## Архитектурные ограничения (КРИТИЧНО)
- **Только SPOT торговля, только LONG позиции** - вся бизнес-логика адаптирована под это
- **Никаких short-позиций** - архитектурное решение, не временное ограничение
- **Маркет-ордера** для входов/выходов (лимитные только для стоп-лоссов)

## Основные характеристики
- **Режимы**: paper (тестовый) и live (боевой) с идентичной логикой
- **Биржа**: Gate.io через CCXT (архитектура поддерживает расширение на другие биржи)
- **Архитектура**: Clean Architecture с автоматическим контролем границ слоев
- **Торговый цикл**: стратегии → фильтры → риски → исполнение → защита → сверка → мониторинг

## Архитектурные принципы (ОБЯЗАТЕЛЬНЫЕ)
1. **Строгое разделение слоев**: app → core (application → domain → infrastructure) → utils
2. **Единая точка исполнения**: ВСЕ сделки ТОЛЬКО через execute_trade.py
3. **Идемпотентность**: защита от дублирования ордеров через client_order_id
4. **Автоматический контроль**: Import Linter блокирует нарушения границ слоев
5. **Единый источник конфигурации**: core/infrastructure/settings.py

## Ключевые особенности

### Безопасность
- **Идемпотентность ордеров**: уникальный client_order_id для каждой сделки
- **Многоуровневые лимиты**: на сделку, по времени (5м), суточные
- **Защитные стоп-ордера**: hard stop-loss и trailing stop  
- **Dead Man's Switch**: автоматическое закрытие при зависании
- **InstanceLock**: блокировка запуска второго экземпляра
- **Throttling**: ограничение частоты запросов к бирже

### Надежность
- **Reconciliation**: регулярная сверка с биржей (балансы, ордера, позиции)
- **Settlement**: обработка частично выполненных ордеров
- **Атомарность операций**: все критичные операции повторяемы
- **WAL-режим SQLite**: безопасный параллельный доступ
- **Автоматическое восстановление**: продолжение работы после сбоев с корректным состоянием

### Масштабируемость и расширяемость
- **Чистая архитектура**: строгое разделение `app → application → domain → infrastructure → utils`
- **Единые точки входа**:
  - `ports.py` — все контракты между слоями
  - `events_topics.py` — реестр всех событий (никаких magic strings)
  - `execute_trade.py` — единственная точка исполнения ордеров
  - `settings.py` — единый источник конфигурации с валидацией
- **Plug & Play модули**: новые стратегии и правила риска подключаются через DI без изменения ядра
- **AI-интеграция**: опциональный слой Fusion (технический 65% + AI 35%), автоматически активируется при наличии модели

### Наблюдаемость
- **Prometheus метрики**: бизнес (PnL, сделки, риски) и технические (латенси, CPU)
- **Health/Ready эндпоинты**: детальный статус всех подсистем
- **Trace ID**: сквозная корреляция всех операций в логах и метриках
- **Структурированные логи**: JSON с контекстом для быстрого поиска проблем

### Управление и отчётность  
- **Telegram-бот управления**: 
  - Команды: `/status`, `/pnl`, `/today`, `/limits`, `/balance`, `/position`
  - Управление: `/pause`, `/resume`, `/stop`, `/health`
  - Whitelist пользователей и ролевая модель
- **Автоматические алерты**: риск-события, режим рынка, системные ошибки
- **Отчёты PnL**: FIFO-учет с комиссиями, суточные/недельные сводки
- **Аудит**: все операции записываются в БД с timestamp и trace_id

## Архитектура

### Принципы (КРИТИЧНО для ИИ и сопровождения)

1. **Зависимости идут ТОЛЬКО сверху вниз** 
   - `app → application → domain → infrastructure → utils`
   - *Utils — низший слой, доступный всем, но никогда не зависит от высших слоёв*

2. **Domain НЕ ЗНАЕТ о внешнем мире**
   - В `domain` только бизнес-правила, стратегии, риск, сигналы
   - Никаких импортов из `app` или `infrastructure`
   - Общение с внешним миром идёт через **порты** (интерфейсы)

3. **Application ↔ Infrastructure только через Ports**
   - `application` работает с `ports.py` (контракты)
   - `infrastructure` реализует эти порты (брокер, шина, БД, макро-источники)
   - Сборка (DI) делается в `app/compose.py`

4. **Единые точки истины**
   - `ports.py` — контракты
   - `events_topics.py` — события
   - `settings.py` — конфигурация
   - `execute_trade.py` — единственная точка открытия ордеров
   - `risk/manager.py` — единый агрегатор правил риска

5. **Import Linter в CI**
   - Автоматически блокирует неправильные импорты
   - Никто не может «обойти» архитектуру

### Диаграмма слоёв

┌──────────────────────────────────────────────┐
│ APP │
│ FastAPI, Telegram, CLI, Compose (DI) │
└───────────────────────┬──────────────────────┘
│ использует
┌───────────────────────▼──────────────────────┐
│ APPLICATION │
│ Orchestrator, Use Cases, Reconciliation │
│ Ports.py (контракты) │
└─────────────┬───────────────────────┬────────┘
│ использует │ реализует
┌─────────────▼────────────┐ ┌──────▼────────────────────┐
│ DOMAIN │ │ INFRASTRUCTURE │
│ Strategies, Signals, │ │ Brokers, DB, Events, │
│ Risk, Macro (Regime) │ │ Macro Sources (HTTP), DMS │
└─────────────┬────────────┘ └──────────┬────────────────┘
│ │
└───────────┬───────────────┘
│
┌──────▼───────┐
│ UTILS │
│ decimal, │
│ pnl, retry, │
│ http, trace │
└──────────────┘

markdown
Копировать код

### Роли слоёв:
- **APP** — только собирает и запускает
- **APPLICATION** — координирует домен и бизнес-процессы
- **DOMAIN** — чистая бизнес-логика (без зависимостей от внешнего мира)
- **INFRASTRUCTURE** — реализует взаимодействие с внешними системами
- **UTILS** — техническая библиотека общих функций

## Структура файлов

crypto-ai-bot/
├── README.md
├── pyproject.toml
├── requirements.txt
├── Makefile
├── Procfile
├── importlinter.ini # Контроль архитектурных границ
├── .env.example
│
├── scripts/ # Утилиты обслуживания
│ ├── backup_db.py
│ ├── rotate_backups.py
│ └── run_server.sh
│
├── tests/
│ ├── unit/
│ ├── integration/
│ ├── e2e/
│ └── fixtures/ # Тестовые данные
│ ├── market_data.json
│ ├── risk_scenarios.json
│ └── orders.json
│
└── src/crypto_ai_bot/
├── app/ # 🔌 Внешние интерфейсы (только сборка и запуск)
│ ├── server.py # FastAPI эндпоинты
│ ├── compose.py # DI композиция (сборка зависимостей)
│ ├── logging_bootstrap.py # Инициализация логирования
│ ├── telegram.py # Telegram publisher (отправка)
│ ├── telegram_bot.py # Telegram bot (прием команд)
│ └── telegram_alerts.py # Alertmanager → Telegram роутинг
│
├── cli/ # CLI утилиты (cab-)
│ ├── smoke.py # Быстрый тест системы
│ ├── maintenance.py # Обслуживание БД
│ ├── reconcile.py # Ручная сверка с биржей
│ ├── performance.py # Отчеты PnL
│ └── health_monitor.py # Мониторинг здоровья
│
├── core/
│ ├── application/ # 🎭 Бизнес-процессы и координация
│ │ ├── orchestrator.py # ⭐ Главный координатор циклов
│ │ ├── ports.py # ⭐ Контракты между слоями
│ │ ├── events_topics.py # ⭐ Реестр всех событий
│ │ ├── protective_exits.py # Логика стоп-лоссов
│ │ │
│ │ ├── use_cases/
│ │ │ ├── execute_trade.py # ⭐ ЕДИНСТВЕННАЯ точка исполнения
│ │ │ └── partial_fills.py # Settlement частичных ордеров
│ │ │
│ │ ├── reconciliation/ # Сверка с биржей
│ │ │ ├── orders.py
│ │ │ ├── positions.py
│ │ │ └── balances.py
│ │ │
│ │ ├── regime/
│ │ │ └── gated_broker.py # Фильтр по режиму рынка
│ │ │
│ │ ├── policies/ # Дефолтные политики
│ │ │ └── intervals.py # Интервалы процессов
│ │ │
│ │ └── monitoring/
│ │ └── health_checker.py # Watchdog системы
│ │
│ ├── domain/ # 💎 Чистая бизнес-логика
│ │ ├── risk/
│ │ │ ├── manager.py # ⭐ Агрегатор всех risk rules
│ │ │ ├── policies.py # Дефолтные soft limits
│ │ │ └── rules/ # Правила риска:
│ │ │ ├── loss_streak.py
│ │ │ ├── max_drawdown.py
│ │ │ ├── daily_loss.py
│ │ │ ├── cooldown.py
│ │ │ ├── spread_cap.py
│ │ │ └── correlation.py
│ │ │
│ │ ├── strategies/ # Торговые стратегии
│ │ │ ├── ema_atr.py
│ │ │ ├── ema_cross.py
│ │ │ ├── rsi_momentum.py
│ │ │ ├── bollinger_bands.py
│ │ │ ├── donchian_breakout.py
│ │ │ ├── supertrend.py
│ │ │ ├── stochastic_adx.py
│ │ │ ├── keltner_squeeze.py
│ │ │ ├── vwap_reversion.py
│ │ │ └── strategy_manager.py # Агрегация стратегий (first|vote|weighted)
│ │ │
│ │ ├── signals/
│ │ │ ├── timeframes.py # Адаптивные веса ТФ
│ │ │ ├── fusion.py # Tech + AI слияние (ИИ здесь)
│ │ │ ├── ai_model.py # AI-модель (опционально)
│ │ │ └── feature_pipeline.py
│ │ │
│ │ └── macro/
│ │ ├── regime_detector.py # ⭐ 4-уровневый режим рынка
│ │ └── types.py
│ │
│ └── infrastructure/ # 🔧 Реализации внешних систем
│ ├── settings.py # ⭐ ЕДИНСТВЕННЫЙ источник конфигурации
│ ├── settings_schema.py # Валидация ENV
│ │
│ ├── brokers/ # Адаптеры бирж
│ │ ├── base.py
│ │ ├── factory.py
│ │ ├── ccxt_adapter.py # Gate.io через CCXT
│ │ ├── live.py
│ │ └── paper.py # Эмуляция для тестов
│ │
│ ├── events/ # Шина событий
│ │ ├── bus.py # In-memory
│ │ ├── bus_adapter.py # Выбор реализации
│ │ └── redis_bus.py # Redis pub/sub
│ │
│ ├── macro_sources/ # ✅ ПРАВИЛЬНОЕ место для HTTP-адаптеров
│ │ ├── dxy.py # HTTP источник DXY
│ │ ├── btc_dominance.py # HTTP источник BTC.D
│ │ └── fomc.py # HTTP источник FOMC
│ │
│ ├── safety/ # Механизмы безопасности
│ │ ├── dead_mans_switch.py
│ │ └── instance_lock.py
│ │
│ └── storage/ # Персистентность
│ ├── facade.py # StoragePort реализация
│ ├── sqlite_adapter.py # SQLite engine
│ ├── backup.py
│ └── migrations/ # SQL миграции
│ ├── runner.py
│ └── V.sql
│
└── utils/ # 🛠 Вспомогательные функции
├── decimal.py # Операции с деньгами
├── pnl.py # FIFO расчеты
├── metrics.py # Prometheus метрики
├── logging.py # Структурированные логи
├── retry.py # Exponential backoff
├── http_client.py # HTTP с таймаутами
├── symbols.py # Нормализация пар
├── time.py # UTC операции
└── trace.py # Trace ID генерация

markdown
Копировать код

### Ключевые файлы (помечены ⭐)
- `orchestrator.py` — главный координатор
- `ports.py` — контракты между слоями
- `events_topics.py` — реестр событий
- `execute_trade.py` — единственная точка исполнения
- `risk/manager.py` — агрегатор risk rules
- `regime_detector.py` — 4-уровневый режим
- `settings.py` — единственный источник конфигурации

### Архитектурные правила расположения
1. **app/** — только точки входа и DI
2. **application/** — координация и use cases
3. **domain/** — чистая бизнес-логика
4. **infrastructure/** — ВСЕ внешние адаптеры (HTTP, DB, Redis)
5. **utils/** — техническая библиотека

## Стратегия торговли

### Основной принцип
- **Торговый таймфрейм**: 15 минут (все сигналы входа/выхода)
- **Анализ тренда**: старшие таймфреймы (1ч, 4ч, 1д, 1н) только для подтверждения направления
- **Правило**: НЕ торговать против тренда старших таймфреймов

### Этапы торгового цикла

1. **Анализ тренда (Trend Confirmation)**
   - **Адаптивные веса таймфреймов** (автоматически корректируются по волатильности):
     - Базовые: 1ч (40%), 4ч (30%), 1д (20%), 1н (10%)
     - При высоком ATR на старшем ТФ → его вес увеличивается
     - При низкой волатильности → вес снижается
     - Сумма весов всегда = 1.0 (автонормализация)
   - Реализация: `signals/timeframes.py` + `feature_pipeline.py`

2. **Генерация сигналов (15m только)**
   - Применяются стратегии:
     - Тренд: `ema_atr`, `ema_cross`, `supertrend`, `donchian_breakout`
     - Моментум/осцилляторы: `rsi_momentum`, `stochastic_adx`
     - Каналы/волатильность/среднее: `bollinger_bands`, `keltner_squeeze`, `vwap_reversion`
   - Проверяем соответствие тренду старших ТФ
   - Фильтр качества: (TODO) подтверждение объёмом

3. **Fusion (опционально)**
   - Технический сигнал: 65%
   - AI-модель сигнал: 35%
   - *Важно:* ИИ подключается **не** в менеджере стратегий, а здесь (в `signals/fusion.py`) вместе с `ai_model.py`

4. **Агрегация стратегий**
   - Режимы: `first` (первая), `vote` (голосование), `weighted` (взвешенное голосование)
   - Управляется настройками (см. ниже «Стратегии в ENV»)

5. **Фильтр режима рынка (Regime Filter) - 4 состояния**
   - **Автоматическое определение** (не через ENV):
     - `risk_on` (score > 0.5) — полный размер позиции
     - `risk_small` (0 < score ≤ 0.5) — 50% от FIXED_AMOUNT
     - `neutral` (-0.5 ≤ score ≤ 0) — только выходы, входы запрещены
     - `risk_off` (score < -0.5) — полная блокировка новых сделок
   - **Расчёт score** на основе:
     - DXY изменение → негативный балл при росте
     - BTC.D изменение → негативный балл при росте
     - FOMC события → негативный балл за N часов до/после
   - Реализация: `domain/macro/regime_detector.py` + `gated_broker.py`

6. **Risk Management (обязательный этап)**
   - **Критические правила** (полная остановка):
     - Max Drawdown превышен
     - Daily Loss Limit достигнут
     - Loss Streak критический
   - **Мягкие правила** (снижение размера позиции):
     - Cooldown активен
     - Spread выше среднего
     - Anti-Correlation warning
   - **Мониторинг правила** (только логирование):
     - Orders/Turnover за 5 минут

7. **Исполнение (execute_trade.py)**
   - Генерация уникального client_order_id
   - Проверка идемпотентности
   - Smart retry с экспоненциальным backoff
   - Детальный лог ошибок для анализа

8. **Protective Exits - многоступенчатая система**
   - **Вход в позицию**:
     - Hard Stop-Loss: -X% от входа
     - Take Profit 1 (TP1): +Y% (закрыть 50%)
     - Take Profit 2 (TP2): +Z% (закрыть остаток)
   - **После TP1**: перевод SL в безубыток
   - **Trailing Stop**: активируется после TP1

9. **Settlement & Reconciliation**
   - Settlement: обработка частичных исполнений
   - Reconciliation: сверка каждые N секунд
   - **Алерты при систематических расхождениях** (>3 раза подряд)

10. **Watchdog - расширенный мониторинг**
    - Здоровье системы (БД, брокер, шина)
    - **Задержки API** (если >1сек систематически)
    - **Отсутствие сигналов** (если >1ч без сигналов)
    - **Лаги reconciliation** (если сверка занимает >10сек)
    - Dead Man's Switch при любой аномалии

## Конфигурация

### Философия конфигурации
- **ENV** = только критичное (среда, безопасность, ключевые лимиты)
- **Код** = умные дефолты, адаптивная логика, политики
- **Override** = ENV может переопределить дефолты из кода (редко)

### ENV переменные (только критичные)

#### 🔴 Среда и безопасность
```env
# Обязательные
MODE=paper|live                    # Режим торговли
EXCHANGE=gateio                    # Биржа
SYMBOLS=BTC/USDT,ETH/USDT         # Торговые пары

# API доступ (для live)
API_KEY=xxx                        # Ключ биржи
API_SECRET=xxx                     # Секрет биржи
API_TOKEN=random-string            # Токен HTTP API
💰 Критические торговые параметры
env
Копировать код
FIXED_AMOUNT=50                    # Размер позиции (USDT)

# Защитные выходы
STOP_LOSS_PCT=5.0                  
TRAILING_STOP_PCT=3.0              
TAKE_PROFIT_1_PCT=2.0              
TAKE_PROFIT_2_PCT=5.0              

# Критические риск-лимиты
RISK_MAX_DRAWDOWN_PCT=10.0        
RISK_DAILY_LOSS_LIMIT_QUOTE=100   
RISK_LOSS_STREAK_COUNT=3          
📡 Внешние сервисы
env
Копировать код
# Telegram (опционально)
TELEGRAM_BOT_TOKEN=xxx             
TELEGRAM_CHAT_ID=-100xxx           
TELEGRAM_ALLOWED_USERS=123,456     

# Макро-источники (URL only)
REGIME_DXY_URL=https://...         
REGIME_BTC_DOM_URL=https://...     
REGIME_FOMC_URL=https://...        

# Инфраструктура
EVENT_BUS_URL=redis://localhost:6379/0  
DB_PATH=./data/trader.sqlite3           
LOG_LEVEL=INFO                          
⚙️ Стратегии (опционально — для тонкой настройки)
Если не задать — по умолчанию активна ema_atr, режим агрегации first, минимальная уверенность 0.0, веса по 1.0.

env
Копировать код
# Управление стратегиями
STRATEGY_ENABLED=true
STRATEGY_SET=ema_atr,donchian_breakout,supertrend,stochastic_adx,keltner_squeeze,vwap_reversion
STRATEGY_MODE=vote                  # first | vote | weighted
STRATEGY_MIN_CONFIDENCE=0.50
STRATEGY_WEIGHTS=ema_atr:1.0,donchian_breakout:1.2,supertrend:1.0,stochastic_adx:0.9,keltner_squeeze:1.1,vwap_reversion:0.8

# Параметры EMA/ATR (используются ema_atr и др., при отсутствии берутся дефолты из кода)
EMA_SHORT=12
EMA_LONG=26
ATR_PERIOD=14
ATR_MAX_PCT=1000
EMA_MIN_SLOPE=0
В КОДЕ (не в ENV)
domain/signals/timeframes.py
python
Копировать код
class AdaptiveTimeframeWeights:
    """Веса автоматически корректируются по ATR"""
    BASE_WEIGHTS = {
        '1h': 0.40,
        '4h': 0.30,
        '1d': 0.20,
        '1w': 0.10
    }
    
    def calculate_weights(self, atr_data):
        # Адаптивная логика на основе волатильности
        # Высокий ATR → больше вес этого ТФ
        pass
domain/risk/policies.py
python
Копировать код
# Мягкие правила (константы)
class SoftRiskDefaults:
    COOLDOWN_SEC = 60
    MAX_SPREAD_PCT = 0.5
    MAX_SLIPPAGE_PCT = 1.0
    MAX_ORDERS_5M = 5
    MAX_TURNOVER_5M_QUOTE = 1000
domain/macro/regime_detector.py
python
Копировать код
class RegimeThresholds:
    """Автоматический расчет режима"""
    DXY_CHANGE_PCT = 0.35
    BTC_DOM_CHANGE_PCT = 0.60
    FOMC_BLOCK_HOURS = 8
    
    def calculate_score(self) -> RegimeState:
        # Возвращает: risk_on | risk_small | neutral | risk_off
        pass
application/policies/intervals.py
python
Копировать код
# Интервалы фоновых процессов
class BackgroundIntervals:
    RECONCILE_SEC = 60
    SETTLEMENT_SEC = 30
    WATCHDOG_SEC = 3
    HEALTH_CHECK_SEC = 10
Приоритет загрузки
python
Копировать код
# В settings.py
def get_config_value(key, default):
    # 1. Проверить ENV
    if env_value := os.getenv(key):
        return env_value
    # 2. Вернуть дефолт из кода
    return default

# Пример использования
cooldown = get_config_value(
    'RISK_COOLDOWN_SEC',  # Редкий override через ENV
    SoftRiskDefaults.COOLDOWN_SEC  # Обычно из кода
)
✅ Преимущества подхода
ENV короткий и понятный — только критичное

Логика в коде — версионируется, тестируется

Работает из коробки — минимум конфигурации

Гибкость — можно переопределить через ENV при необходимости

⚠️ Валидация при запуске
Проверка обязательных ENV (MODE, EXCHANGE, SYMBOLS)

Критические лимиты > 0

API ключи для live режима

При ошибке → детальное сообщение и выход

Getting Started (Быстрый старт)
Минимальные требования
Python 3.11+

512 MB RAM

1 GB свободного места (БД + логи)

Стабильное интернет-соединение

Первый запуск за 5 минут
bash
Копировать код
# 1. Клонировать проект
git clone <repo> && cd crypto-ai-bot

# 2. Создать окружение
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .

# 3. Минимальная конфигурация
cat > .env << EOF
MODE=paper
EXCHANGE=gateio
SYMBOLS=BTC/USDT
FIXED_AMOUNT=50
LOG_LEVEL=INFO
EOF

# 4. Smoke Test
cab-smoke

# 5. Запуск
uvicorn crypto_ai_bot.app.server:app

# 6. Проверка
curl http://localhost:8000/health
Запуск
Режимы запуска
Paper Trading (тестовый)
env
Копировать код
MODE=paper
# API ключи НЕ нужны
# Эмуляция ордеров локально
Live Trading (боевой)
env
Копировать код
MODE=live
API_KEY=xxx       # ОБЯЗАТЕЛЬНО
API_SECRET=xxx    # ОБЯЗАТЕЛЬНО
CLI команды (cab-*)
bash
Копировать код
# Тестирование
cab-smoke                # Быстрая проверка всех систем

# База данных
cab-maintenance backup   # Резервная копия БД
cab-maintenance vacuum   # Оптимизация БД
cab-maintenance integrity # Проверка целостности

# Операции
cab-reconcile           # Ручная сверка с биржей
cab-perf               # Отчет PnL за сутки

# Мониторинг
cab-health-monitor --oneshot  # Проверка health статуса
HTTP API эндпоинты
bash
Копировать код
# Статус и мониторинг
GET  /health              # Детальный статус всех систем
GET  /ready               # Готовность (200 OK или 503)
GET  /metrics             # Prometheus метрики

# Управление (требует API_TOKEN)
GET  /orchestrator/status?symbol=BTC/USDT
POST /orchestrator/start?symbol=BTC/USDT   # Headers: Authorization: Bearer <API_TOKEN>
POST /orchestrator/pause?symbol=BTC/USDT
POST /orchestrator/resume?symbol=BTC/USDT
POST /orchestrator/stop?symbol=BTC/USDT

# Отчеты
GET  /pnl/today?symbol=BTC/USDT
Telegram команды
bash
Копировать код
/status    # Статус всех торговых пар
/pnl       # PnL детальный
/today     # Сводка за день
/balance   # Баланс счета
/position  # Открытые позиции
/limits    # Использование лимитов

# Управление
/pause     # Приостановить торговлю
/resume    # Возобновить торговлю
/stop      # Остановить бота
/health    # Проверка здоровья
Production деплой
Railway/Heroku
yaml
Копировать код
# Procfile
web: uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port $PORT
worker: cab-health-monitor --daemon
Docker
dockerfile
Копировать код
# Dockerfile (базовый)
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["uvicorn", "crypto_ai_bot.app.server:app", "--host", "0.0.0.0", "--port", "8000"]
Systemd
ini
Копировать код
# /etc/systemd/system/crypto-bot.service
[Service]
ExecStart=/path/to/venv/bin/uvicorn crypto_ai_bot.app.server:app
Restart=always
Environment="PATH=/path/to/venv/bin"
⚠️ Важно для продакшена
InstanceLock автоматически предотвращает двойной запуск

Dead Man's Switch закроет позиции при зависании

Reconciliation исправит расхождения с биржей

Health endpoint для мониторинга внешними системами

Тестирование
Уровни тестирования
1. Smoke Test (быстрая проверка)
bash
Копировать код
cab-smoke  # ~5 секунд
# ✓ Подключение к бирже (paper mode)
# ✓ Инициализация БД
# ✓ Полный цикл: сигнал → риск → mock-ордер
2. Unit Tests (компоненты)
bash
Копировать код
pytest tests/unit -v --cov --cov-fail-under=80
# Фокус:
# - Каждое risk rule отдельно
# - Стратегии на тестовых данных
# - Идемпотентность ордеров
# - PnL расчеты (FIFO)
3. Integration Tests (связки)
bash
Копировать код
pytest tests/integration -m "not slow"
# - Orchestrator → RiskManager → ExecuteTrade
# - Reconciliation с mock биржей
# - EventBus → Telegram mock
# - Settlement частичных ордеров
4. E2E Test (полный прогон)
bash
Копировать код
pytest tests/e2e --paper-mode --duration=2h
# - Запуск в paper mode на 2 часа
# - Реальные рыночные данные
# - Фиксация всех событий
# - Сравнение с эталонным прогоном
5. Static Analysis
bash
Копировать код
# Архитектурные границы (КРИТИЧНО)
import-linter --config importlinter.ini

# Типы
mypy src/crypto_ai_bot --strict

# Качество кода
ruff check src/

# Секреты (pre-commit hook)
detect-secrets scan
Test Fixtures
bash
Копировать код
tests/fixtures/
├── market_data.json         # OHLCV данные для стратегий
├── risk_scenarios.json      # Edge-cases для risk rules
├── orders.json              # Частичные исполнения, phantom orders
├── regime_states.json       # Состояния режима (risk_on/off/small/neutral)
└── reconciliation_cases.json # Расхождения биржа/БД
Критичные тест-кейсы
Безопасность и надежность
python
Копировать код
# Идемпотентность
def test_no_duplicate_orders()
def test_idempotency_after_restart()

# Защита от двойного запуска
def test_instance_lock()
def test_instance_lock_cleanup_on_crash()

# Dead Man's Switch
def test_dms_triggers_on_freeze()
def test_dms_closes_position_correctly()

# Rate limiting
def test_api_rate_limit_throttling()
def test_burst_protection()
Risk Management
python
Копировать код
# Критические правила (полная остановка)
def test_loss_streak_blocks_all()
def test_daily_limit_stops_trading()
def test_max_drawdown_emergency_stop()

# Мягкие правила (снижение размера)
def test_cooldown_delays_next_trade()
def test_spread_blocks_entry_not_exit()

# Режимы рынка
def test_neutral_mode_blocks_entry_allows_exit()
def test_risk_small_reduces_position_50pct()
def test_risk_off_blocks_all_entries()
Protective Exits
python
Копировать код
def test_trailing_stop_moves_up_only()
def test_tp1_moves_sl_to_breakeven()
def test_multi_stage_exit_execution()
Reconciliation
python
Копировать код
def test_position_mismatch_auto_corrected()
def test_phantom_order_cleanup()
def test_systematic_mismatch_alerts()
CI/CD Pipeline
yaml
Копировать код
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  security:
    - detect-secrets scan
    - safety check (dependencies)
  
  quality:
    - import-linter (architecture)
    - mypy (types)
    - ruff (style)
    
  tests:
    - pytest unit --cov-fail-under=80
    - pytest integration
    - cab-smoke
    
  e2e:
    - if: branch == main
      run: pytest e2e --paper-mode --duration=1h
Специальные правила тестирования
При изменении критичных модулей
bash
Копировать код
# risk/manager.py изменен
make test-risk-all

# execute_trade.py изменен  
make test-idempotency
make test-settlement

# reconciliation/* изменен
make test-reconciliation-suite

# regime_detector.py изменен
make test-regime-states
PR Checklist (обязательно)
 Новая фича = новый тест

 CI зеленый

 Coverage > 80%

 Import Linter passed

 No secrets in code

 Risk rules протестированы на всех сценариях

Локальный прогон всего
bash
Копировать код
make test-all  # Запускает полный цикл проверок
Мониторинг
Что предоставляет бот
Эндпоинты
bash
Копировать код
# Детальное состояние (JSON)
curl http://localhost:8000/health

# Готовность (200 или 503)
curl http://localhost:8000/ready

# Prometheus метрики
curl http://localhost:8000/metrics | grep crypto_
Метрики (экспортируемые ботом)
Бизнес-метрики

prometheus
Копировать код
crypto_pnl_realized_total{symbol="BTC/USDT"}
crypto_trades_total{symbol="BTC/USDT", status="completed"}
crypto_position_size{symbol="BTC/USDT"}
crypto_risk_blocked_total{rule="loss_streak"}
crypto_regime_state{state="risk_on|risk_small|neutral|risk_off"}
Технические метрики

prometheus
Копировать код
crypto_cycle_duration_ms{phase="signals|risk|execute"}
crypto_api_latency_ms{endpoint="ticker|order"}
crypto_reconciliation_duration_ms
crypto_health_status{component="db|broker|eventbus"}
Структурированные логи
json
Копировать код
{
  "timestamp": "2025-01-10T12:00:00Z",
  "level": "INFO",
  "trace_id": "abc123",  // ОБЯЗАТЕЛЬНО для каждого цикла
  "module": "orchestrator",
  "symbol": "BTC/USDT",
  "message": "Signal generated",
  "context": {...}
}
Trace ID (критично)
Каждый цикл orchestrator генерирует уникальный trace_id

Пробрасывается через все операции (логи, метрики, события)

Видно в Telegram алертах для корреляции

Связывает метрики ↔ логи ↔ алерты

Внешний мониторинг
⚠️ Вся инфраструктура мониторинга в отдельном репозитории:

bash
Копировать код
https://github.com/YOUR_ORG/crypto-bot-monitoring
Там находятся:

Prometheus конфигурация (scrape jobs, retention 30 дней)

Alertmanager правила и роутинг

Grafana дашборды (PnL, Risk, Performance панели)

Docker Compose для деплоя стека

Terraform/Ansible скрипты

Alert Rules (основные)
Критические (действие немедленно)
yaml
Копировать код
BotDown: up == 0 for 1m
DeadMansSwitchTriggered: crypto_dms_triggered_total > 0
MaxDrawdownExceeded: crypto_drawdown_current_pct > 10
Важные (проверить в течение часа)
yaml
Копировать код
NoTradesLongTime: rate(crypto_trades_total[1h]) == 0 for 2h
HighAPILatency: crypto_api_latency_ms > 1000 for 5m
NeutralTooLong: crypto_regime_state == "neutral" for 4h
Информационные
yaml
Копировать код
RiskBlockedFrequent: rate(crypto_risk_blocked_total[5m]) > 0.5
RegimeChanged: crypto_regime_state != offset 5m
Telegram интеграция
Критические → мгновенно с trace_id

Важные → батчинг 5 минут

Инфо → сводка раз в час

Anti-spam защита от дублей

Retention политика
Метрики Prometheus: 30 дней (конфиг в crypto-bot-monitoring)

Логи: 90 дней (ротация через logrotate или cloud provider)

БД бэкапы: 7 дней daily, 4 недели weekly

Примеры использования
Проверка здоровья
bash
Копировать код
# Быстрая проверка
curl -s http://localhost:8000/ready && echo "OK" || echo "FAIL"

# Детальная диагностика
curl -s http://localhost:8000/health | jq .components
Поиск по trace_id
bash
Копировать код
# В логах
grep "trace_id.*abc123" /var/log/crypto-bot.log

# В метриках
curl http://localhost:8000/metrics | grep 'trace_id="abc123"'
⚠️ Правила мониторинга
Метрики не блокируют торговлю (async export)

Алерты actionable (не шум, а конкретные действия)

Trace ID обязателен для всех операций

Dashboard real-time (обновление 15 сек)

Separation of concerns: бот только экспортирует, мониторинг в отдельном сервисе

Troubleshooting
InstanceLock не освобождается
Симптом: "Instance already running"

Решение:

bash
Копировать код
rm -f /tmp/crypto-bot.lock
# Если Redis:
redis-cli DEL crypto-bot:instance:lock
Reconciliation всегда находит расхождения
bash
Копировать код
timedatectl   # Проверить, что сервер в UTC
cab-reconcile --force-sync
Risk Manager блокирует все сделки
bash
Копировать код
curl http://localhost:8000/orchestrator/status?symbol=BTC/USDT
# Сброс дневных счётчиков (осторожно!)
sqlite3 data/trader.sqlite3 "DELETE FROM risk_counters WHERE date < date('now')"
Telegram не работает
bash
Копировать код
curl https://api.telegram.org/bot<TOKEN>/getMe
curl https://api.telegram.org/bot<TOKEN>/getUpdates
Roadmap / TODO
В разработке (v1.1)
 Multi-stage exits (TP1/TP2 + SL в безубыток)

 Адаптивные веса таймфреймов (ATR)

 4-уровневый режим рынка (risk_on/small/neutral/off)

 Нелинейный Fusion (AI confidence → tech weight)

Планируется (v1.2)
 Множественные биржи

 Grid-trading для флэта

 Basket-trading (корзина активов)

 Web-интерфейс мониторинга

Backlog (идеи)
 Short позиции (требует редизайна)

 Options/Futures

 Social sentiment анализ

 ML-оптимизация параметров

Contributing Guidelines
Архитектурные правила
Domain не импортирует из Infrastructure

Application работает только через Ports

Новые адаптеры → только в infrastructure/

Единые точки входа
Новые события → events_topics.py

Новые настройки → сначала в код, потом в ENV

Ордера → только через execute_trade.py

Добавление стратегии
python
Копировать код
# domain/strategies/my_strategy.py
from .base import BaseStrategy, Decision, MarketData, StrategyContext

class MyStrategy(BaseStrategy):
    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision:
        # Возвратить Decision(action="buy"|"sell"|"hold", confidence: float, reason: str)
        return Decision(action="hold", reason="not_implemented")

# strategy_manager.py
AVAILABLE = "STRATEGY_SET via settings"  # имена, разделённые запятыми
# Пример ENV:
# STRATEGY_SET=ema_atr,donchian_breakout,supertrend
Добавление risk rules
python
Копировать код
# domain/risk/rules/my_rule.py
class MyRule(BaseRule):
    def check(self, context) -> RuleResult:
        pass

# risk/manager.py
self.rules.append(MyRule())
Checklist перед коммитом
 make test-all зелёный

 Import Linter не ругается

 Новый код покрыт тестами

 Trace ID пробрасывается

 События используют events_topics.py

 README обновлён

Performance
Средние показатели
RAM: 200–300 MB (idle), до 500 MB при активной торговле

CPU: <5% среднее, пики до 20% (reconciliation)

Латенси цикла: 50–200 ms

API: ~500 запросов/час (ticker), ~20/час (orders)

БД: ~10 MB/месяц/пара

Логи: ~100 MB/день (INFO)

Оптимизация
WAL mode SQLite (по умолчанию)

Redis EventBus при >3 парах

LOG_LEVEL=WARNING для продакшена

Увеличить RECONCILE_INTERVAL_SEC при редких сделках

Контакты
Проект поддерживается и развивается внутри команды. Для вопросов по архитектуре или внесения вклада вы можете связаться с автором и главным разработчиком: Sabir Şahbaz (GitHub: sabiraka1).

Для новых участников команды: по всем организационным моментам (доступы к Railway, переменным окружения, ключам API) обращайтесь к тимлиду или DevOps инженеру.

Спасибо за интерес к проекту crypto-ai-bot! Надеемся, этот README поможет вам соблюдать архитектурную целостность при разработке.