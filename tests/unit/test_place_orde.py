import pytest
from types import SimpleNamespace
from crypto_ai_bot.core.use_cases import place_order

class DummyBroker:
    """Dummy broker to simulate exchange responses."""
    def __init__(self, ticker_data=None, order_result=None, raise_on_order=False):
        # ticker_data should be a dict with keys 'bid', 'ask', 'last'
        self._ticker = ticker_data or {"bid": 100.0, "ask": 100.0, "last": 100.0}
        # order_result simulates the return of broker.create_order
        self._order_result = order_result or {"id": "12345", "price": 100.0, "amount": 1.0}
        self._raise_on_order = raise_on_order
        self.order_called = False

    def fetch_ticker(self, symbol):
        # Return preset ticker data
        return self._ticker

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        # Simulate order placement; optionally raise an exception
        self.order_called = True
        # Ensure Gate.io client order id is present and well-formed
        assert params and isinstance(params.get("text"), str) and params["text"].startswith("t-")
        if self._raise_on_order:
            raise RuntimeError("Simulated order failure")
        return self._order_result

class DummyTradesRepo:
    """Dummy trades repository to capture record calls."""
    def __init__(self):
        self.last_payload = None
        self.record_called = False

    def record(self, trade_payload):
        # Simulate recording a trade, store payload for verification
        self.record_called = True
        self.last_payload = trade_payload

class DummyPositionsRepo:
    """Dummy positions repository to simulate open positions."""
    def __init__(self, has_position=False):
        self.has_position = has_position

    def get_open(self):
        # If has_position, return a dummy open position
        if self.has_position:
            return [{"symbol": "BTC-USDT", "qty": 1.0, "avg_price": 100.0}]
        return []

    def get_qty(self, symbol):
        # Alternate interface to get quantity for symbol
        return 1.0 if self.has_position else 0.0

class DummyIdempotencyRepo:
    """Dummy idempotency repository to control idempotency behavior."""
    def __init__(self, allow=True):
        self.allow = allow
        self.stored_keys = set()
        self.committed_keys = set()

    def check_and_store(self, key, ttl_seconds=300):
        # Return False if duplicate not allowed, True otherwise
        if not self.allow:
            return False
        if key in self.stored_keys and key not in self.committed_keys:
            return False
        self.stored_keys.add(key)
        return True

    def commit(self, key):
        # Mark key as committed
        if key in self.stored_keys:
            self.committed_keys.add(key)

class DummyLimiter:
    """Dummy rate limiter to simulate rate limit behavior."""
    def __init__(self, allow=True):
        self.allow = allow
        self.calls = 0

    def try_acquire(self, token):
        self.calls += 1
        return self.allow

def make_config(**kwargs):
    """Create a simple config object with given attributes."""
    defaults = {
        "SYMBOL": "BTC/USDT",
        "MAX_SPREAD_BPS": 50.0,
        "SLIPPAGE_BPS": 20.0,
        "TAKER_FEE_BPS": 10.0,
        "POSITION_SIZE_USD": 100.0
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)

def test_place_order_sell_no_position():
    """Тест: попытка продажи без открытой позиции возвращает ошибку 'no_long_position'."""
    cfg = make_config()
    broker = DummyBroker()
    positions_repo = DummyPositionsRepo(has_position=False)  # нет открытых позиций
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    result = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="sell",
        idempotency_repo=idem_repo
    )
    assert result["accepted"] is False
    assert result["error"] == "no_long_position"

def test_place_order_duplicate_request():
    """Тест: повторный запрос с тем же ключом идемпотентности возвращает 'duplicate_request'."""
    cfg = make_config()
    broker = DummyBroker()
    positions_repo = DummyPositionsRepo(has_position=True)  # имитируем открытую позицию
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo(allow=True)
    # Первый вызов (должен пройти успешно)
    result1 = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    # Второй вызов с тем же ключом (симулируем дубликат)
    idem_repo.allow = False
    result2 = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result2["accepted"] is False
    assert result2["error"] == "duplicate_request"
    assert "idempotency_key" in result2 and result2["idempotency_key"] is not None

def test_place_order_no_price_or_spread():
    """Тест: при отсутствии цены или слишком широком спреде возвращаются соответствующие ошибки."""
    cfg = make_config(MAX_SPREAD_BPS=50.0)
    # Случай 1: нет актуальной цены (last=0)
    broker1 = DummyBroker(ticker_data={"bid": 0.0, "ask": 0.0, "last": 0.0})
    positions_repo = DummyPositionsRepo(has_position=True)
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    result1 = place_order.place_order(
        cfg=cfg,
        broker=broker1,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result1["accepted"] is False
    assert result1["error"] == "no_price"
    # Случай 2: спред слишком широкий (bid и ask далеко друг от друга)
    broker2 = DummyBroker(ticker_data={"bid": 100.0, "ask": 120.0, "last": 110.0})
    result2 = place_order.place_order(
        cfg=cfg,
        broker=broker2,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result2["accepted"] is False
    assert result2["error"] == "spread_too_wide"

def test_place_order_zero_notional():
    """Тест: если размер позиции (POSITION_SIZE_USD) равен 0, возвращается ошибка 'zero_notional'."""
    cfg = make_config(POSITION_SIZE_USD=0.0)  # нулевой объем позиции
    broker = DummyBroker()
    positions_repo = DummyPositionsRepo(has_position=True)
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    result = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result["accepted"] is False
    assert result["error"] == "zero_notional"

def test_place_order_rate_limited():
    """Тест: при срабатывании rate limiter запрос отклоняется с ошибкой 'rate_limited'."""
    cfg = make_config()
    broker = DummyBroker()
    positions_repo = DummyPositionsRepo(has_position=True)
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    limiter = DummyLimiter(allow=False)  # ограничение срабатывает
    # Внедряем limiter в конфиг
    cfg.limiter = limiter
    result = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result["accepted"] is False
    assert result["error"] == "rate_limited"
    assert limiter.calls == 1

def test_place_order_broker_exception():
    """Тест: если broker.create_order выбрасывает исключение, возвращается ошибка 'broker_error'."""
    cfg = make_config()
    broker = DummyBroker(raise_on_order=True)  # будет бросать ошибку при размещении ордера
    positions_repo = DummyPositionsRepo(has_position=True)
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    result = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    assert result["accepted"] is False
    assert result["error"] == "broker_error"
    # Проверяем, что даже при ошибке попытка опубликовать событие OrderExecuted была (async, без проверки результата)

def test_place_order_successful_buy():
    """Тест: успешное открытие позиции (buy) через place_order с корректной записью сделки."""
    cfg = make_config(POSITION_SIZE_USD=50.0)  # положительный объем позиции
    broker = DummyBroker(
        ticker_data={"bid": 100.0, "ask": 101.0, "last": 100.5},
        order_result={"id": "ABC123", "price": 100.5, "amount": 0.5}
    )
    positions_repo = DummyPositionsRepo(has_position=False)
    trades_repo = DummyTradesRepo()
    idem_repo = DummyIdempotencyRepo()
    idem_repo.allow = True
    result = place_order.place_order(
        cfg=cfg,
        broker=broker,
        trades_repo=trades_repo,
        positions_repo=positions_repo,
        exits_repo=None,
        symbol="BTC/USDT",
        side="buy",
        idempotency_repo=idem_repo
    )
    # Успешный результат
    assert result["accepted"] is True
    assert result.get("error") is None
    # Должны быть возвращены ключ идемпотентности и ненулевые цена/количество
    assert result.get("idempotency_key") is not None
    assert result["executed_price"] == pytest.approx(100.5, rel=1e-3)
    assert result["executed_qty"] == pytest.approx(0.5, rel=1e-3)
    # Broker.create_order должен быть вызван
    assert broker.order_called is True
    # Сделка должна быть записана в репозиторий
    assert trades_repo.record_called is True
    assert trades_repo.last_payload is not None
    payload = trades_repo.last_payload
    # В info должны присутствовать idempotency_key и client_order_id
    assert payload["info"].get("idempotency_key") == result["idempotency_key"]
    client_id = payload["info"].get("client_order_id")
    assert isinstance(client_id, str) and client_id.startswith("t-")
    # Параметры сделки должны соответствовать выполненным цене и количеству
    assert payload["price"] == pytest.approx(100.5, rel=1e-3)
    assert payload["qty"] == pytest.approx(0.5, rel=1e-3)
    assert payload["side"] == "buy"
