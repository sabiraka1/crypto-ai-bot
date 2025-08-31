import types

import pytest

from crypto_ai_bot.app.adapters.telegram_bot import TelegramBotCommands


class _DummyAlerts:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.sent: list[str] = []
    async def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


@pytest.mark.asyncio
async def test_tg_commands_cache_and_help(monkeypatch):
    # Подменяем TelegramAlerts внутри модуля
    import crypto_ai_bot.app.adapters.telegram_bot as mod
    monkeypatch.setattr(mod, "TelegramAlerts", _DummyAlerts)

    class _Orch:
        def status(self):
            return {"started": False, "paused": False, "loops": {}}
        async def pause(self): pass
        async def resume(self): pass
        async def stop(self): pass

    container = types.SimpleNamespace(
        orchestrators={"BTC/USDT": _Orch()},
        risk=types.SimpleNamespace(config=types.SimpleNamespace(
            cooldown_sec=60, max_spread_pct=0.3, max_position_base=0.02,
            max_orders_per_hour=6, daily_loss_limit_quote=100,
            max_fee_pct=0.1, max_slippage_pct=0.1,
        )),
        storage=types.SimpleNamespace(
            trades=types.SimpleNamespace(
                pnl_today_quote=lambda s: 0,
                daily_turnover_quote=lambda s: 0,
                count_orders_last_minutes=lambda s, m: 0,
            )
        ),
        health=types.SimpleNamespace(get_snapshot=lambda: {
            "ok_storage": True, "ok_broker": True, "ok_bus": True, "ts": 0
        }),
        broker=types.SimpleNamespace(fetch_balance=lambda: {"BTC": {"free": 0}, "USDT": {"free": 0}}),
    )

    bot = TelegramBotCommands(
        bot_token="x", allowed_users=[], container=container, default_symbol="BTC/USDT", long_poll_sec=1
    )

    # /help — кладёт ответ в cache, повторный вызов берёт из cache
    await bot._cmd_help(chat_id=1)
    assert (1, "help") in bot._cache
    old_ts, old_txt = bot._cache[(1, "help")]
    await bot._cmd_help(chat_id=1)
    assert bot._cache[(1, "help")][0] >= old_ts


@pytest.mark.asyncio
async def test_tg_commands_set_and_status(monkeypatch):
    import crypto_ai_bot.app.adapters.telegram_bot as mod
    monkeypatch.setattr(mod, "TelegramAlerts", _DummyAlerts)

    class _Orch:
        def __init__(self):
            self._paused = False
        def status(self):
            return {"started": True, "paused": self._paused, "loops": {}}
        async def pause(self): self._paused = True
        async def resume(self): self._paused = False
        async def stop(self): self._paused = False

    container = types.SimpleNamespace(orchestrators={"BTC/USDT": _Orch()})
    bot = TelegramBotCommands(
        bot_token="x", allowed_users=[], container=container, default_symbol="BTC/USDT"
    )

    # Смена символа
    await bot._cmd_set(chat_id=1, text="/set BTC/USDT")
    assert bot._chat_symbol[1] == "BTC/USDT"

    # Статус
    await bot._cmd_status(chat_id=1, symbol="BTC/USDT")
