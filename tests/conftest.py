import os, sys, pathlib, pytest

@pytest.fixture(scope="session")
def prepared_env(tmp_path_factory):
    # Ensure src/ is on sys.path
    proj_root = pathlib.Path(__file__).resolve().parents[2]
    src_dir = proj_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    os.environ["PYTHONPATH"] = "src"

    # Minimal runtime env
    os.environ.setdefault("MODE", "paper")
    os.environ.setdefault("SYMBOL", "BTC/USDT")
    os.environ.setdefault("TIMEFRAME", "1h")
    os.environ.setdefault("ENABLE_TRADING", "true")
    os.environ.setdefault("DEFAULT_ORDER_SIZE", "0.01")
    os.environ.setdefault("IDEMPOTENCY_TTL_SECONDS", "300")
    os.environ.setdefault("TIME_DRIFT_LIMIT_MS", "1000")
    os.environ.setdefault("HEALTH_TIME_TIMEOUT_S", "1.0")

    # Isolated DB per session
    db_dir = tmp_path_factory.mktemp("db")
    os.environ["DB_PATH"] = str(db_dir / "test.sqlite")

    return {"root": proj_root}

@pytest.fixture(scope="session")
def client(prepared_env):
    # Import after env is set
    from fastapi.testclient import TestClient
    from crypto_ai_bot.app.server import app
    return TestClient(app)
