import types

import pytest
from fastapi import status
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_server_health_and_status(monkeypatch):
    # Импортируем сервер после monkeypatch build_container_async
    from crypto_ai_bot.app import server as srv

    class _Orch:
        def __init__(self):
            self._started = False
        def status(self):
            return {"started": self._started, "paused": False, "loops": {}}
        async def start(self):
            self._started = True
        async def stop(self):
            self._started = False
        async def pause(self):
            pass
        async def resume(self):
            pass

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

    # ЕДИНСТВЕННОЕ ИЗМЕНЕНИЕ - используем ASGITransport
    transport = ASGITransport(app=srv.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data["ok"] is True
        assert data["default_symbol"] == "BTC/USDT"

        r2 = await ac.get("/orchestrator/status")
        assert r2.status_code == status.HTTP_200_OK
        assert r2.json()["symbol"] == "BTC/USDT"