import types
from decimal import Decimal
from crypto_ai_bot.core.infrastructure.storage.repositories import Storage
from crypto_ai_bot.utils.time import now_ms

def test_trades_repo_basic(mock_storage: Storage) -> None:
    """Базовые операции с репозиторием сделок (совместимо с getattr(...) в реализациях)."""
    st = mock_storage

    # Вместо dict используем объект с атрибутами — так работает add_from_order(...)
    order = types.SimpleNamespace(
        id="x1",
        broker_order_id="x1",
        client_order_id="cid",
        clientOrderId="cid",  # совместимость, если код читает оба
        symbol="BTC/USDT",
        side="buy",
        amount=Decimal("0.001"),
        filled=Decimal("0.001"),
        price=Decimal("10000"),
        cost=Decimal("10"),
        fee_quote=Decimal("0.01"),
        ts_ms=now_ms(),
        timestamp=now_ms(),
        status="closed",
    )

    st.trades.add_from_order(order)

    rows = st.trades.list_today("BTC/USDT")
    assert rows and rows[-1]["symbol"] == "BTC/USDT"
