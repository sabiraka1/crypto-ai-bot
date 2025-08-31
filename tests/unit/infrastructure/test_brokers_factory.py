from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker


class _DummyPaper:
    class PaperBroker:
        def __init__(self, *, settings):
            self.settings = settings


class _DummyCcxt:
    class CcxtBroker:
        def __init__(self, *, exchange, api_key, api_secret, api_password, timeout_sec, proxy, settings):
            self.kw = dict(exchange=exchange, api_key=api_key, api_secret=api_secret,
                           api_password=api_password, timeout_sec=timeout_sec, proxy=proxy, settings=settings)


def test_make_broker_paper(monkeypatch, mock_settings):
    # подменим поиск модуля, чтобы точно нашёлся PaperBroker
    from crypto_ai_bot.core.infrastructure import brokers as _pkg
    monkeypatch.setattr(_pkg.factory, "_import_first", lambda *c: _DummyPaper)
    b = make_broker(exchange="gateio", mode="paper", settings=mock_settings)
    assert isinstance(b, _DummyPaper.PaperBroker)


def test_make_broker_live(monkeypatch, mock_settings):
    from crypto_ai_bot.core.infrastructure import brokers as _pkg
    monkeypatch.setattr(_pkg.factory, "_import_first", lambda *c: _DummyCcxt)
    b = make_broker(exchange="gateio", mode="live", settings=mock_settings)
    assert isinstance(b, _DummyCcxt.CcxtBroker)
    assert b.kw["exchange"] == "gateio"
