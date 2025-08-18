# ------- Config -------
PY ?= python3
UVICORN ?= uvicorn
APP ?= crypto_ai_bot.app.server:app
HOST ?= 0.0.0.0
PORT ?= 8000

export PYTHONPATH := src

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
	pytest -q

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

# ------- Format (опционально, если установлены) -------
.PHONY: lint
lint:
	-ruff check src tests

.PHONY: fmt
fmt:
	-ruff check --select I --fix src tests
	-black src tests
