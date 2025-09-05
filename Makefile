.PHONY: install run worker test lint type import-lint smoke up down format pre-commit

install:
\tpython -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

run:
\tuvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port 8000

worker:
\tpython -m crypto_ai_bot.cli.health_monitor

lint:
\truff check src

format:
\truff check --fix src && ruff format src

type:
\tmypy --config-file mypy.ini

import-lint:
\tlint-imports

test:
\tpytest -q

smoke:
\tpython -m crypto_ai_bot.cli.cab_smoke

up:
\tdocker compose up -d --build

down:
\tdocker compose down
