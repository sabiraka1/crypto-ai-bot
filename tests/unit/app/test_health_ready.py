import pytest
from httpx import ASGITransport, AsyncClient
from crypto_ai_bot.app.server import app, READY_FLAG

@pytest.mark.asyncio
async def test_health_always_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_ready_toggles_status_code():
    READY_FLAG["ready"] = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/ready")
        assert r.status_code == 503
        READY_FLAG["ready"] = True
        r = await ac.get("/ready")
        assert r.status_code == 200
