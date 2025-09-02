import types
import pytest
from httpx import AsyncClient
from httpx import ASGITransport
from starlette import status

@pytest.mark.asyncio
async def test_server_health_and_status(monkeypatch):
    from crypto_ai_bot.app import server as srv

    class _Orch:
        def __init__(self):
            # Стартуем «как бы запущенным», чтобы /health был 200
            self._started = True
        def status(self):
            return {"started": self._started, "paused": False, "loops": {}}
        async def start(self): self._started = True
        async def stop(self): self._started = False
        async def pause(self): pass
        async def resume(self): pass

    class _Container:
        settings = types.SimpleNamespace(SYMBOL="BTC/USDT")
        orchestrators = {"BTC/USDT": _Orch()}
        storage = types.SimpleNamespace(trades=types.SimpleNamespace(
            pnl_today_quote=lambda s: 0,
            daily_turnover_quote=lambda s: 0,
            count_orders_today=lambda s: 0,
        ))
        bus = types.SimpleNamespace()
        broker = types.SimpleNamespace()

    async def _build():
        return _Container()

    monkeypatch.setattr(srv, "build_container_async", _build)

    transport = ASGITransport(app=srv.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
        assert r.status_code == status.HTTP_200_OK

        # Для полноты — проверим /status
        r2 = await ac.get("/status")
        assert r2.status_code == status.HTTP_200_OK
