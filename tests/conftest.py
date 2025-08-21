import os, tempfile, asyncio, pytest
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
async def container():
    c = build_container()
    yield c
    await c.bus.close()
    try:
        if hasattr(c.broker, "close"):
            maybe = c.broker.close()
            if getattr(maybe, "__await__", None):
                await maybe
    except Exception:
        pass
    c.storage.conn.close()
