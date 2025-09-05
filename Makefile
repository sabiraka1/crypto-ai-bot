.PHONY: lint format type imports test test-all test-unit test-integ test-smoke test-risk-all test-idempotency test-settlement ci

# Форматирование (ruff)
format:
	ruff format src/

# Линтер (ruff)  
lint:
	ruff check .

# Статическая типизация (mypy)
type:
	PYTHONPATH=src mypy src/

# Архитектурные зависимости (import-linter)
imports:
	lint-imports -c importlinter.ini

# --- ТЕСТЫ ---

# Быстрый smoke test
test-smoke:
	cab-smoke

# Unit тесты
test-unit:
	MODE=paper EXCHANGE=gateio SYMBOLS=BTC/USDT DB_PATH=":memory:" \
	PYTHONPATH=src pytest tests/unit -v --cov --cov-fail-under=80

# Integration тесты
test-integ:
	MODE=paper EXCHANGE=gateio SYMBOLS=BTC/USDT DB_PATH=":memory:" \
	PYTHONPATH=src pytest tests/integration -m "not slow"

# Все тесты риск-менеджмента
test-risk-all:
	PYTHONPATH=src pytest tests/unit/risk -v

# Тесты идемпотентности
test-idempotency:
	PYTHONPATH=src pytest tests/unit/test_idempotency.py -v

# Тесты settlement
test-settlement:
	PYTHONPATH=src pytest tests/unit/test_settlement.py -v

# Основной набор тестов
test:
	MODE=paper EXCHANGE=gateio SYMBOLS=BTC/USDT DB_PATH=":memory:" \
	PYTHONPATH=src pytest -q

# Полный набор тестов (как в README)
test-all: lint type imports test-unit test-integ test-smoke

# --- CI/CD ---

# Полный прогон CI (все шаги)
ci: format lint type imports test

# --- DOCKER ---

# Сборка Docker образа
docker-build:
	docker build -t crypto-ai-bot:latest .

# Запуск через docker-compose
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

# --- ОБСЛУЖИВАНИЕ БД ---

backup:
	cab-maintenance backup

vacuum:
	cab-maintenance vacuum

integrity:
	cab-maintenance integrity