# ------- Config -------
PY ?= python
UVICORN ?= uvicorn
APP ?= crypto_ai_bot.app.server:app
HOST ?= 0.0.0.0
PORT ?= 8000

export PYTHONPATH := src

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

# ------- Tests & checks -------
.PHONY: test
test:
	pytest -v --maxfail=1 --disable-warnings -q

.PHONY: coverage
coverage:
	pytest --cov=src --cov-report=term-missing

.PHONY: check-arch
check-arch:
	chmod +x scripts/check_architecture.sh
	./scripts/check_architecture.sh

# ------- Quick helpers -------
.PHONY: health
health:
	curl -s http://127.0.0.1:$(PORT)/health | jq .

.PHONY: status
status:
	curl -s http://127.0.0.1:$(PORT)/status/extended | jq .

.PHONY: metrics
metrics:
	curl -s http://127.0.0.1:$(PORT)/metrics | head -n 80

.PHONY: chart
chart:
	curl -s "http://127.0.0.1:$(PORT)/chart/test?symbol=BTC/USDT&timeframe=1h&limit=200" > price.svg
	curl -s "http://127.0.0.1:$(PORT)/chart/profit" > equity.svg
	@echo "Saved: price.svg, equity.svg"

# ------- Format & Lint -------
.PHONY: lint
lint:
	-ruff check src tests

.PHONY: fmt
fmt:
	-ruff check --select I --fix src tests
	-black src tests
