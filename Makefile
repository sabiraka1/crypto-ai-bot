.PHONY: lint type imports test ci

# Линтер (ruff)
lint:
	ruff check .

# Статическая типизация (mypy)
type:
	PYTHONPATH=src mypy src/

# Архитектурные зависимости (import-linter)
imports:
	lint-imports -c importlinter.ini

# Тесты (pytest с in-memory базой)
test:
	MODE=paper EXCHANGE=gateio SYMBOL=BTC/USDT DB_PATH=":memory:" PYTHONPATH=src pytest -q

# Полный прогон CI (все шаги)
ci: lint type imports test
