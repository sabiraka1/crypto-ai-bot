import pytest
from httpx import AsyncClient, ASGITransport
from crypto_ai_bot.app.server import app

@pytest.mark.anyio
async def test_endpoints_live_ready_health_metrics(monkeypatch):
    monkeypatch.setenv("MODE", "paper")

    # Явно запускаем lifespan приложения (startup/shutdown)
    try:
        lifespan_ctx = app.router.lifespan_context  # FastAPI/Starlette >= 0.27
    except AttributeError:
        async def lifespan_ctx(_):  # fallback (ничего не делает)
            class _CM:
                async def __aenter__(self): pass
                async def __aexit__(self, *exc): pass
            return _CM()

    async with lifespan_ctx(app):
        transport = ASGITransport(app=app)  # без lifespan=
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/live")
            assert r1.status_code == 200 and r1.json().get("ok") is True

            r2 = await ac.get("/ready")
            assert r2.status_code in {200, 503}

            r3 = await ac.get("/health")
            assert r3.status_code in {200, 503}
            assert "db_ok" in r3.json()

            r4 = await ac.get("/metrics")
            assert r4.status_code == 200
            ct = r4.headers.get("content-type", "")
            assert ("text/plain" in ct) or ("application/json" in ct) or (r4.json().get("realized_pnl") is not None)
