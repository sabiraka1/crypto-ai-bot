import pytest

@pytest.mark.asyncio
async def test_market_data_ticker_and_ohlcv_parsing(market_data, paper_broker, symbol):
    # тикер
    t = await market_data.get_ticker(symbol)
    assert t is not None
    assert str(t.symbol) == symbol
    assert t.bid <= t.ask
    # ohlcv (стаб может вернуть пусто — это допустимо)
    candles = await market_data.get_ohlcv(symbol, timeframe="15m", limit=10)
    assert isinstance(candles, list)
