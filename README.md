# crypto-ai-bot

Long-only автотрейдинг криптовалют (Gate.io, расширяемо на другие биржи).  
Единый пайплайн: **evaluate → risk → place_order → protective_exits → reconcile → watchdog**.

## ⚡ Быстрый старт

### 1) Установка
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip wheel
pip install -e .
2) Конфигурация
Скопируйте .env.example в .env и при необходимости измените переменные (режим, символ, лимиты, ключи для live).

3) Запуск (безопасный)
bash
Копировать
Редактировать
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000
4) Smoke-проверки
bash
Копировать
Редактировать
# health:
python - <<'PY'
import asyncio
from crypto_ai_bot.app.compose import build_container
async def main():
    c = build_container()
    rep = await c.health.check(symbol=c.settings.SYMBOL)
    print("MODE=", c.settings.MODE, "SANDBOX=", c.settings.SANDBOX, "ok=", rep.ok, rep.components)
asyncio.run(main())
PY
🎛️ Режимы (одна логика)
PAPER: MODE=paper (симулятор, без реальных ордеров). Источник цены: PRICE_FEED=fixed|live.

LIVE-SANDBOX: MODE=live, SANDBOX=1 (если тестнет доступен в CCXT).

LIVE-PROD: MODE=live, SANDBOX=0 (боевые ключи). Включается InstanceLock, DMS.

🔐 Безопасность и риск-менеджмент
Идемпотентность (bucket + TTL).

Cooldown, спред-лимит, max position base, max orders/hour, дневной loss-limit.

Dead Man’s Switch, Protective exits.

Token-auth для mgmt API (API_TOKEN).

🔄 Сверки
Запускаются из оркестратора:

OrdersReconciler — открытые ордера (если брокер поддерживает fetch_open_orders).

PositionsReconciler — локальная позиция vs биржевой баланс (BalanceDTO).

BalancesReconciler — free-балансы.

🗄️ База данных / миграции / бэкапы
Миграции выполняются автоматически при старте. CLI:

bash
Копировать
Редактировать
# миграция:
PYTHONPATH=src python -m crypto_ai_bot.core.storage.migrations.cli migrate --db ./data/trader.sqlite3

# бэкап:
PYTHONPATH=src python -m crypto_ai_bot.core.storage.migrations.cli backup --db ./data/trader.sqlite3 --retention-days 30
📊 Наблюдаемость
GET /health — сводный health.

GET /metrics — Prometheus (с JSON-фолбэком, если нет клиента).

⚙️ Переменные окружения (ключевые)
См. .env.example. Важные: MODE, SANDBOX, EXCHANGE, SYMBOL|SYMBOLS, FIXED_AMOUNT,
DB_PATH, IDEMPOTENCY_*, RISK_*, интервалы оркестратора, API_TOKEN, (для live) API_KEY|API_SECRET.

🧱 Архитектура
Слои: utils → core → app.
Брокеры: PaperBroker (симулятор), CcxtBroker (live/sandbox).
Все ENV читаются в core/settings.py. Импорты — только пакетные from crypto_ai_bot.utils....

⚠️ Дисклеймер
Торговля криптовалютой связана с риском. Используете на свой страх и риск.