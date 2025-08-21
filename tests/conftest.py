import os, pytest, asyncio, inspect, tempfile
from pathlib import Path
from crypto_ai_bot.app.compose import build_container

# Глобальные дефолты для всех тестов
@pytest.fixture(scope="session", autouse=True)
def _configure_env():
    os.environ.setdefault("MODE", "paper")
    os.environ.setdefault("SYMBOL", "BTC/USDT")
    os.environ.setdefault("EXCHANGE", "gateio")
    # прометheus не обязателен; если установлен — ок

# Контейнер с УНИКАЛЬНОЙ БД на каждый тест
@pytest.fixture
def container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "testdb.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    # (опционально) маленький TTL, чтобы не мешали ключи из прошедших секунд в рамках одного теста
    monkeypatch.setenv("IDEMPOTENCY_TTL_SEC", "60")

    c = build_container()
    yield c

    # teardown: аккуратно закрыть ресурсы из sync-функции
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(c.bus.close())
        except Exception:
            pass
        try:
            if hasattr(c.broker, "close"):
                res = c.broker.close()
                if inspect.isawaitable(res):
                    loop.run_until_complete(res)
        except Exception:
            pass
    finally:
        try:
            c.storage.conn.close()
        except Exception:
            pass

# чтобы anyio не требовал trio
@pytest.fixture
def anyio_backend():
    return "asyncio"
