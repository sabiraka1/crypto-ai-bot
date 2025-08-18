# tests/test_app_tick.py
import os
import tempfile
from fastapi.testclient import TestClient

# подготовим чистую среду до импорта app
os.environ["MODE"] = "paper"
tmpdb = tempfile.NamedTemporaryFile(prefix="bot_", suffix=".db", delete=True)
os.environ["DB_PATH"] = tmpdb.name

from crypto_ai_bot.app.server import app  # noqa: E402

def test_tick_endpoint_paper_mode():
    client = TestClient(app)
    r = client.post("/tick", json={"symbol": "BTC/USDT", "timeframe": "1h", "limit": 50})
    assert r.status_code == 200
    data = r.json()
    # важно, чтобы не было «error»
    assert data.get("status") in {"ok", "blocked_by_risk", "hold", "rate_limited"}
