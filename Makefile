.PHONY: help install dev-install lock run run-paper run-live lint fmt type test \
        migrate backup ci-smoke docker-build docker-run

PYTHON      ?= python
UVICORN     ?= uvicorn
APP         ?= crypto_ai_bot.app.server:app
PORT        ?= 8000

help:
	@echo "Targets: install | dev-install | run | run-paper | run-live | lint | fmt | type | test | migrate | backup | ci-smoke | docker-build | docker-run"

install:
	$(PYTHON) -m pip install -U pip wheel
	$(PYTHON) -m pip install -e .

dev-install: install
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(UVICORN) $(APP) --host 0.0.0.0 --port $(PORT)

run-paper:
	MODE=paper SANDBOX=0 $(UVICORN) $(APP) --host 0.0.0.0 --port $(PORT)

run-live:
	MODE=live SANDBOX=0 $(UVICORN) $(APP) --host 0.0.0.0 --port $(PORT)

lint:
	ruff check .

fmt:
	ruff check --fix .
	isort src tests || true
	black src tests || true

type:
	mypy src

test:
	pytest -q

migrate:
	PYTHONPATH=src $(PYTHON) -m crypto_ai_bot.core.storage.migrations.cli migrate --db $${DB_PATH:-./data/trader.sqlite3}

backup:
	PYTHONPATH=src $(PYTHON) -m crypto_ai_bot.core.storage.migrations.cli backup --db $${DB_PATH:-./data/trader.sqlite3} --retention-days $${BACKUP_RETENTION_DAYS:-30}

ci-smoke:
	PYTHONPATH=src $(PYTHON) - <<'PY'
import sqlite3
from crypto_ai_bot.core.storage.migrations.runner import run_migrations
from crypto_ai_bot.utils.time import now_ms
conn = sqlite3.connect('data/ci-smoketest.sqlite3')
conn.row_factory = sqlite3.Row
print('version=', run_migrations(conn, now_ms=now_ms(), db_path='data/ci-smoketest.sqlite3', do_backup=False))
PY

docker-build:
	docker build -t crypto-ai-bot:local .

docker-run:
	docker run --rm -p $(PORT):8000 --env-file .env crypto-ai-bot:local

.PHONY: run lint test format

# Запуск сервера (локально)
run:
	uvicorn crypto_ai_bot.app.server:app --reload --host 0.0.0.0 --port 8000

# Проверка импортов (Import Linter)
lint:
	py -m importlinter.cli --config importlinter.ini

# Запуск тестов (pytest)
test:
	pytest -v

# Форматирование кода (black + isort)
format:
	black src
	isort src

