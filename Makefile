# ==========================================
# CRYPTO-AI-BOT MAKEFILE v8.0
# ==========================================

# ------- Config -------
PY ?= python
UVICORN ?= uvicorn
APP ?= crypto_ai_bot.app.server:app
HOST ?= 0.0.0.0
PORT ?= 8000

# Updated for new structure with utils in root
export PYTHONPATH := .:src

# ------- Install -------
.PHONY: install
install:
	$(PY) -m pip install -U pip setuptools wheel
	$(PY) -m pip install -r requirements.txt

.PHONY: dev-install
dev-install:
	$(PY) -m pip install -U pip setuptools wheel
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

# ------- Run -------
.PHONY: run
run:
	$(UVICORN) $(APP) --host $(HOST) --port $(PORT)

.PHONY: dev
dev:
	$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --reload

# ------- Orchestrator -------
.PHONY: start-trading
start-trading:
	curl -X POST http://127.0.0.1:$(PORT)/orchestrator/start

.PHONY: stop-trading
stop-trading:
	curl -X POST http://127.0.0.1:$(PORT)/orchestrator/stop

# ------- Tests -------
.PHONY: test
test:
	pytest -v --maxfail=1 --disable-warnings -q

.PHONY: test-unit
test-unit:
	pytest tests/unit -v

.PHONY: test-integration
test-integration:
	pytest tests/integration -v

.PHONY: coverage
coverage:
	pytest --cov=src --cov=utils --cov-report=term-missing

# ------- Architecture -------
.PHONY: check-arch
check-arch:
	$(PY) -m scripts.arch_check

.PHONY: check-imports
check-imports:
	lint-imports -c importlinter.ini

# ------- Migrations -------
.PHONY: migrate
migrate:
	$(PY) -m scripts.smoke_migrations

# ------- Maintenance -------
.PHONY: backup-db
backup-db:
	$(PY) -m scripts.maintenance_cli backup-db

.PHONY: cleanup
cleanup:
	$(PY) -m scripts.maintenance_cli cleanup-idempotency

.PHONY: vacuum
vacuum:
	$(PY) -m scripts.maintenance_cli vacuum

# ------- Monitoring -------
.PHONY: monitoring-up
monitoring-up:
	cd ops/prometheus && docker-compose up -d

.PHONY: monitoring-down
monitoring-down:
	cd ops/prometheus && docker-compose down

# ------- Quick helpers -------
.PHONY: health
health:
	curl -s http://127.0.0.1:$(PORT)/health | jq .

.PHONY: status
status:
	curl -s http://127.0.0.1:$(PORT)/orchestrator/status | jq .

.PHONY: metrics
metrics:
	curl -s http://127.0.0.1:$(PORT)/metrics | head -n 50

# ------- Format & Lint -------
.PHONY: lint
lint:
	ruff check src tests utils

.PHONY: fmt
fmt:
	ruff check --select I --fix src tests utils
	black src tests utils

# ------- Clean -------
.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
	rm -rf *.egg-info dist build