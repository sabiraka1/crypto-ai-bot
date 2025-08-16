\# crypto-ai-bot — AI трейдинг‑бот (Gate.io) с Telegram и ML



Полноценный README для будущей, целевой структуры проекта. Документ описывает \*\*что лежит в корне репозитория\*\*, как всё устроено, как запускать локально/в облаке (Render, Replit), какие переменные окружения нужны, какие директории и файлы обязательны, а также \*договорённый\* функционал бота: автоматический трейдинг, обучение модели, графики и Telegram‑уведомления.



---



\## TL;DR



\* \*\*Фреймворк\*\*: Flask + APScheduler (бекграунд‑задачи)

\* \*\*Биржа\*\*: Gate.io через `ccxt`

\* \*\*Коммуникации\*\*: Telegram бот (webhook + команды)

\* \*\*ML\*\*: модуль скоровки сигналов, автоперетренировка после закрытых сделок

\* \*\*Данные\*\*: CSV (`sinyal\_fiyat\_analizi.csv`, `closed\_trades.csv`), JSON (`open\_position.json`)

\* \*\*Хостинг\*\*: Railway (Start Command или Procfile); Replit — опционально (.replit)



---



\## Ключевые возможности (target)



\* 📈 Генерация торговых сигналов (RSI, MACD, свечные и графические паттерны)

\* 🤖 ML‑скоровка сигналов и принятие решений (порог автосделок настраивается, по умолчанию ≥ 0.7)

\* 🔁 Авто‑открытие/закрытие позиций (Gate.io/ccxt) + логирование результатов

\* 📊 Автографики (RSI/MACD/паттерны) + сводный график прибыли

\* 🧠 Автоперетренировка модели после каждой закрытой сделки

\* 💬 Команды Telegram: `/start`, `/test`, `/train`, `/profit`, `/errors`, `/status`

\* 🌐 Веб‑эндпоинты (Flask): проверка живости, вебхук Telegram, ручной запуск тестов/обучения



---



\## Архитектура (общее представление)



```

+-------------------+         +---------------------+

| Telegram Bot      | <-----> | Flask App (app.py)  |

| (/start,/status...)|  Webhook /alive,/train,...  |

+-------------------+         +---------------------+

&nbsp;                                     |

&nbsp;                                     v

&nbsp;                            +------------------+

&nbsp;                            | trading\_bot.py   |  <-- ccxt (Gate.io)

&nbsp;                            | trade\_engine.py  |

&nbsp;                            +------------------+

&nbsp;                                     |

&nbsp;                                     v

&nbsp;                +------------------------+     +-------------------+

&nbsp;                | sinyal\_skorlayici.py   |     | technical\_analysis|

&nbsp;                | (ML модель/оценка)     |     | (RSI,MACD,pattern)|

&nbsp;                +------------------------+     +-------------------+

&nbsp;                        |           \\

&nbsp;                        v            v

&nbsp;                 data\_logger.py   grafik\_olusturucu.py

&nbsp;                  (CSV/JSON)         (charts/)

```



---



\## Структура репозитория (целевое состояние)



```

crypto-ai-bot/

├─ app.py                    # Flask-приложение (webhook, /alive, фоновые задачи)

├─ telegram\_bot.py           # Команды Telegram и форматирование сообщений

├─ trading\_bot.py            # Логика сигнал→решение→исполнение

├─ trade\_engine.py           # Работа с ccxt (открытие/закрытие позиций)

├─ technical\_analysis.py     # Индикаторы, свечные и графические паттерны

├─ sinyal\_skorlayici.py      # ML-скоровщик сигналов (обучение/инференс)

├─ data\_logger.py            # Логирование сигналов/сделок в CSV/JSON

├─ grafik\_olusturucu.py      # Генерация графиков (RSI/MACD/паттерны)

├─ position\_status.py        # Утилиты статуса позиции (для /status, /profit)

├─ signal\_analyzer.py        # Анализ ошибочных сигналов (+ GPT-объяснение)

├─ profit\_chart.py           # Сводный график прибыли на основе closed\_trades.csv

│

├─ config.py                 # (или .env) конфигурация/переменные окружения

├─ requirements.txt          # Список зависимостей (pip)

├─ Procfile                  # Render: процесс запуска (gunicorn)

├─ .replit                   # Replit: команда запуска/среда

├─ Dockerfile                # (опционально) контейнеризация

├─ docker-compose.yml        # (опционально) локальный запуск/мониторинг

├─ Makefile                  # (опционально) shortcut-команды разработчика

├─ .env.example              # Шаблон переменных окружения

├─ .gitignore                # Исключения git

├─ LICENSE                   # (опционально) лицензия

├─ README.md                 # Этот документ

│

├─ charts/                   # Автогенерируемые графики (PNG)

├─ data/                     # CSV/JSON данные (см. ниже)

│  ├─ sinyal\_fiyat\_analizi.csv  # История сигналов для обучения (7 колонок)

│  ├─ closed\_trades.csv         # Журнал закрытых сделок

│  └─ open\_position.json        # Текущая открытая позиция

│

├─ logs/                     # Логи приложения/торговли

├─ models/                   # ML-модель(и), например model.pkl

├─ scripts/                  # Утилиты: деплой, миграция, бэкапы

└─ templates/ and static/    # (опционально) веб-панель/предпросмотры

```



> \*\*Важно:\*\* директории `data/`, `charts/`, `logs/`, `models/` должны \*\*создаваться при старте\*\*, если их нет, чтобы запуск был идемпотентным на чистой машине.



---



\## Файлы в корне (обязательные и рекомендованные)



\*\*Обязательные:\*\*



\* `README.md` — текущий документ

\* `requirements.txt` — список зависимостей

\* `.gitignore` — исключения

\* `.env.example` — шаблон переменных окружения (без секретов)

\* `app.py` — точка входа Flask

\* `telegram\_bot.py`, `trading\_bot.py`, `sinyal\_skorlayici.py`, `technical\_analysis.py`, `data\_logger.py`, `grafik\_olusturucu.py`

\* `position\_status.py`, `signal\_analyzer.py`, `profit\_chart.py`

\* `config.py` \*\*или\*\* поддержка `.env` (через `python-dotenv`)



\*\*Для развёртывания (рекомендуется):\*\*



\* `Procfile` — для Railway (опционально; можно указать Start Command в настройках)



&nbsp; \* `web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`

\* `.replit` — для Replit (команда запуска, keep-alive)

\* `Dockerfile` и `docker-compose.yml` — для контейнерного запуска локально/в облаке

\* `Makefile` — команды `make run`, `make train`, `make test`, `make format` и т.п.

\* `LICENSE` — тип лицензии проекта



---



\## Переменные окружения (`.env.example`)



Пример содержимого (шаблон — \*\*не\*\* храните секреты в git):



```

\# Основное

FLASK\_ENV=production

PORT=8000

TZ=Europe/Istanbul



\# Gate.io (ccxt)

EXCHANGE=gateio

GATEIO\_API\_KEY=\_\_FILL\_ME\_\_

GATEIO\_API\_SECRET=\_\_FILL\_ME\_\_

GATEIO\_PASSWORD=\_\_FILL\_ME\_\_           # если требуется биржей



\# Торговля

SYMBOL=BTC/USDT

TIMEFRAME=15m

TRADE\_AMOUNT=10                        # USDT, гибко настраивается

AUTO\_TRADE\_THRESHOLD=0.7               # порог автосделки по AI‑скорe



\# Пути/каталоги

DATA\_DIR=./data

CHARTS\_DIR=./charts

MODELS\_DIR=./models

LOGS\_DIR=./logs

MODEL\_PATH=./models/signal\_model.pkl



\# Telegram

TELEGRAM\_BOT\_TOKEN=\_\_FILL\_ME\_\_

TELEGRAM\_CHAT\_ID=\_\_FILL\_ME\_\_

WEBHOOK\_URL=\_\_FILL\_ME\_\_/telegram/webhook # внешний https URL для webhook



\# Дополнительно

SENTRY\_DSN=

```



---



\## Установка и запуск (локально)



```

python -m venv .venv

source .venv/bin/activate            # Windows: .venv\\Scripts\\activate

pip install -r requirements.txt

cp .env.example .env                 # заполните секреты

python app.py                        # локальный запуск Flask

```



После старта сервис предоставляет:



\* `GET /alive` — проверка живости/версии

\* `POST /telegram/webhook` — приём апдейтов Telegram

\* (опц.) `POST /train-model` — ручной триггер обучения



> На дев‑окружении вместо webhook можно временно использовать polling в `telegram\_bot.py`, но целевой способ — \*\*webhook\*\*.



---



\## Запуск на Railway



1\. \*\*Деплой из GitHub\*\* (рекомендуется): создайте новый Service → \*Deploy from GitHub\* → выберите репозиторий.



&nbsp;  \* Railway автоматически определит Python через Nixpacks и установит зависимости из `requirements.txt`.

2\. \*\*Переменные окружения\*\*: перенесите значения из `.env.example` в Settings → \*Variables\*.



&nbsp;  \* `PORT` задаётся Railway автоматически — в коде используйте его из env, не хардкодьте.

&nbsp;  \* Рекомендуем указать `TZ=Europe/Istanbul`.

3\. \*\*Стартовая команда\*\* (Start Command) \*\*или\*\* `Procfile`:



&nbsp;  \* Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`

&nbsp;  \* Либо добавьте в корень `Procfile` со строкой: `web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`

4\. \*\*Персистентные данные (Volume)\*\*: добавьте \*Volume\* и примонтируйте его, например, в `/data`.



&nbsp;  \* В Variables переопределите пути: `DATA\_DIR=/data`, `CHARTS\_DIR=/data/charts`, `MODELS\_DIR=/data/models`, `LOGS\_DIR=/data/logs`.

&nbsp;  \* При старте приложение должно создать подкаталоги, если их нет.

5\. \*\*Webhook Telegram\*\*:



&nbsp;  \* После первого деплоя возьмите публичный домен Railway (например, `https://<service>.up.railway.app`).

&nbsp;  \* Установите `WEBHOOK\_URL=https://<domain>/telegram/webhook`.

&nbsp;  \* Пример ручной регистрации вебхука:



&nbsp;    ```bash

&nbsp;    curl -X POST "https://api.telegram.org/bot$TELEGRAM\_BOT\_TOKEN/setWebhook" \\

&nbsp;         -d "url=$WEBHOOK\_URL"

&nbsp;    ```

6\. \*\*Проверка\*\*: `GET /alive` должен возвращать OK/версию/время. Логи смотрите во вкладке \*Logs\*.

7\. \*\*Примечания\*\*:



&nbsp;  \* Используйте backend `Agg` для matplotlib (см. `requirements.txt`/инициализацию графиков).

&nbsp;  \* Не используйте долгие блокирующие операции в обработчиках вебхука — выносите в фоновые задачи.



\## Запуск на Replit



\* Проверьте файл `.replit`:



```

run = "python app.py"

```



\* Используется эндпоинт `GET /alive` как keep‑alive.



---



\## Команды Telegram (цель)



\* `/start` — приветствие + краткая справка

\* `/status` — текущее состояние позиции (из `open\_position.json`), PnL

\* `/test` — форс‑генерация сигнала, отправка AI‑score и графика

\* `/train` — ручная перетренировка ML‑модели (по `sinyal\_fiyat\_analizi.csv`)

\* `/profit` — агрегированная прибыль + график из `closed\_trades.csv`

\* `/errors` — анализ «ложных» сигналов и объяснения причин (GPT‑интерпретация)



---



\## Данные и форматы



\*\*`data/sinyal\_fiyat\_analizi.csv`\*\* — обучающая история сигналов (минимум 7 колонок):



```

timestamp,symbol,timeframe,signal,ai\_score,price,outcome

```



\* `signal` ∈ {BUY, SELL, NONE}

\* `outcome` — факт после задержки (например, +%/-% через N минут/свечей)



\*\*`data/closed\_trades.csv`\*\* — журнал закрытых сделок:



```

opened\_at,closed\_at,symbol,side,qty,entry\_price,exit\_price,pnl\_abs,pnl\_pct,reason

```



\*\*`data/open\_position.json`\*\* — текущая открытая позиция:



```

{

&nbsp; "symbol": "BTC/USDT",

&nbsp; "side": "buy",

&nbsp; "qty": 0.001,

&nbsp; "entry\_price": 65000.0,

&nbsp; "opened\_at": "2025-08-01T12:34:56Z"

}

```



> Все пути берутся из env (`DATA\_DIR`, `CHARTS\_DIR`), файлы создаются автоматически при первом использовании.



---



\## Основные модули



\* \*\*`technical\_analysis.py`\*\* — RSI, MACD, ADX, Bollinger, SMA/EMA, объём, stochastic + свечные паттерны (doji, hammer, shooting star, engulfing и пр.) + базовый поиск уровней поддержки/сопротивления.

\* \*\*`sinyal\_skorlayici.py`\*\* — обучение/инференс ML‑модели на `sinyal\_fiyat\_analizi.csv`, выдаёт `ai\_score ∈ \[0,1]`.

\* \*\*`trading\_bot.py`\*\* — объединяет TA и ML, принимает решение: `NONE/BUY/SELL` и триггерит `trade\_engine`.

\* \*\*`trade\_engine.py`\*\* — ccxt/Gate.io. Авто‑открытие/закрытие по правилам: TP (+2%), RSI > 85, max‑время удержания (напр. 2 часа).

\* \*\*`data\_logger.py`\*\* — ведёт CSV/JSON логи: сигналы, сделки, результат, AI‑оценки.

\* \*\*`grafik\_olusturucu.py`\*\* — строит PNG‑графики (RSI/MACD/паттерны), сохраняет в `charts/`.

\* \*\*`signal\_analyzer.py`\*\* — детект «ложных» сигналов + текстовые объяснения причин (поддержка GPT).

\* \*\*`position\_status.py`\*\* — агрегирует состояние для `/status` и `/profit`.



---



\## Веб‑эндпоинты (Flask)



\* `GET /alive` — ok/версия/время

\* `POST /telegram/webhook` — входящий Telegram update

\* `POST /train-model` — (опционно) обучение модели

\* `POST /test-signal` — (опционно) триггер тестового сигнала



> Все эндпоинты валидируют вход, пишут логи и возвращают JSON.



---



\## Логи и мониторинг



\* Логи пишутся в `logs/` (ротация по размеру/дням)

\* (Опц.) `/metrics` Prometheus — добавьте при переходе на прод



---



\## Тесты (миnimum)



\* Юнит‑тесты для TA, скоровщика, торговых правил

\* Интеграционный тест «сигнал→ордер→закрытие→обучение» (использовать paper‑режим)



Запуск:



```

pytest -q

```



---



\## Makefile (пример целей)



```

make install   # pip install -r requirements.txt

make run       # локальный запуск

make train     # ручная тренировка модели

make test      # pytest

make format    # ruff/black

```



---



\## Дорожная карта (укрупнённо)



\* P0: стабильный webhook, автосделки по порогу, корректное закрытие позиций, CSV‑логи, команды Telegram

\* P1: график прибыли, `/profit`, автоперетренировка после закрытия

\* P2: Prometheus `/metrics`, Docker, CI, алерты, веб‑панель



---



\## Лицензия



Укажите желаемую лицензию в `LICENSE` (например, MIT/Apache‑2.0).



---



\### Примечание



README отражает \*\*целевое\*\* состояние. По мере реализации держите список «обязательных корневых файлов» и «переменных окружения» актуальными — это основной ориентир для развёртывания и поддержки.



