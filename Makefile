# --------
# Makefile для crypto-ai-bot
# Быстрые команды: установка, формат/линт/типы/тесты, запуск сервера и вспомогательные задачи.
# --------

PY := python
PIP := python -m pip
PKG := crypto_ai_bot
SRC := src
UVICORN := uvicorn $(PKG).app.server:app --host 0.0.0.0 --port $${PORT:-8000}

.DEFAULT_GOAL := help

help:  ## показать справку
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Установка ---

venv:  ## создать виртуальное окружение .venv
	@test -d .venv || $(PY) -m venv .venv
	@echo "Activate: source .venv/bin/activate (Linux/macOS) / .\.venv\Scripts\Activate.ps1 (Windows)"

install:  ## установить зависимости (prod)
	$(PIP) install -U pip wheel
	@if [ -f requirements.txt ]; then $(PIP) install -r requirements.txt ; fi
	$(PIP) install -e .

install-dev: install  ## установить dev-инструменты (ruff, mypy, pytest, import-linter)
	$(PIP) install ruff mypy pytest import-linter

# --- Качество кода ---

fmt:  ## авто-правки кода (ruff)
	ruff check $(SRC) --fix

lint:  ## линт кода (ruff, строгий режим)
	ruff check $(SRC)

types:  ## типизация (mypy)
	mypy $(SRC)

imports:  ## проверка импорт-контрактов (Import Linter)
	lint-imports --config importlinter.ini

qa: lint types imports  ## все проверки качества

# --- Тесты ---

test:  ## запустить тесты
	pytest -q

# --- Запуск сервера и утилиты ---

run:  ## локальный запуск Uvicorn
	$(UVICORN)

run-gunicorn:  ## прод-подобный запуск (gunicorn + uvicorn worker)
	gunicorn -w $${WEB_CONCURRENCY:-2} -k uvicorn.workers.UvicornWorker \
		--bind 0.0.0.0:$${PORT:-8000} $(PKG).app.server:app

redis:  ## быстро поднять Redis (через docker) для EVENT_BUS_URL=redis://localhost:6379/0
	docker run --rm -it -p 6379:6379 redis:7-alpine

# --- БД и обслуживание ---

db.backup:  ## резервное копирование БД
	$(PY) -m $(PKG).cli.maintenance backup

db.rotate:  ## ротация бэкапов (по умолчанию 30 дней)
	$(PY) -m $(PKG).cli.maintenance rotate --days $${DAYS:-30}

db.vacuum:  ## VACUUM
	$(PY) -m $(PKG).cli.maintenance vacuum

db.integrity:  ## проверка целостности
	$(PY) -m $(PKG).cli.maintenance integrity

db.list:  ## показать список бэкапов
	$(PY) -m $(PKG).cli.maintenance list

# --- Сервисные команды ---

smoke:  ## проверка сборки/запуска
	$(PY) -m $(PKG).cli.smoke

health:  ## разовый health-чек HTTP сервера (ожидает запущенный сервер)
	$(PY) -m $(PKG).cli.health_monitor --oneshot --url $${HEALTH_URL:-http://127.0.0.1:8000/health}

perf:  ## отчёт за сегодня (FIFO/PNL/частота)
	$(PY) -m $(PKG).cli.performance

ci: qa test  ## как в CI: качество + тесты

.PHONY: help venv install install-dev fmt lint types imports qa test run run-gunicorn redis \
        db.backup db.rotate db.vacuum db.integrity db.list smoke health perf ci
