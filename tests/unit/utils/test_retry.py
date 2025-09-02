import asyncio
import pytest

from crypto_ai_bot.utils.retry import async_retry

@pytest.mark.asyncio
async def test_async_retry_eventual_success():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    res = await async_retry(flaky, retries=5, base_delay=0.01)
    assert res == "ok"
    assert calls["n"] == 3

@pytest.mark.asyncio
async def test_async_retry_gives_up():
    async def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await async_retry(always_fail, retries=2, base_delay=0.01)
