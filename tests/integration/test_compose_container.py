import pytest


@pytest.mark.asyncio
async def test_build_container_async_min(monkeypatch, tmp_path):
    # Изолируем БД во временной папке
    db_path = tmp_path / "t.sqlite3"

    from crypto_ai_bot.core.infrastructure import settings as settings_mod
    orig_load = settings_mod.Settings.load

    def _fake_load():
        s = orig_load()
        s.DB_PATH = str(db_path)
        s.SYMBOL = "BTC/USDT"
        s.SYMBOLS = ""
        s.TELEGRAM_BOT_COMMANDS_ENABLED = 0
        s.EVENT_BUS_URL = ""  # AsyncEventBus
        s.MODE = "paper"
        return s

    monkeypatch.setattr(settings_mod.Settings, "load", staticmethod(_fake_load))

    from crypto_ai_bot.app.compose import build_container_async
    c = await build_container_async()

    # Проверяем, что контейнер собран и содержит оркестратор по символу
    assert getattr(c, "orchestrators", {}).get("BTC/USDT") is not None
