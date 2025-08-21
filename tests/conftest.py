import os, tempfile, pytest, asyncio, inspect
from crypto_ai_bot.app.compose import build_container

@pytest.fixture(scope="session", autouse=True)
def _configure_env():
    os.environ.setdefault("MODE", "paper")
    os.environ.setdefault("SYMBOL", "BTC/USDT")
    os.environ.setdefault("EXCHANGE", "gateio")
    fd, path = tempfile.mkstemp(prefix="cab_tests_", suffix=".db")
    os.close(fd)
    os.environ["DB_PATH"] = path
    yield
    try: os.remove(path)
    except OSError: pass

@pytest.fixture
def container():
    c = build_container()
    yield c
    # --- teardown: закрываем аккуратно в синхронной фикстуре
    try:
        # берём текущий цикл или создаём новый
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # bus.close()
        try:
            loop.run_until_complete(c.bus.close())
        except Exception:
            pass

        # broker.close() если он async
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

# Ограничим anyio только asyncio-бэкендом (чтобы не тянуть trio)
@pytest.fixture
def anyio_backend():
    return "asyncio"
