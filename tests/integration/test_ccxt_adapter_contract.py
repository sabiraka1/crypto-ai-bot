from decimal import Decimal
from typing import Any, Dict

import pytest

from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
from crypto_ai_bot.utils.decimal import dec


class _FakeExchange:
    def __init__(self) -> None:
        self._mk = {
            "btc_usdt": {"precision": {"amount": 0.0001, "price": 0.1}, "limits": {"cost": {"min": 5}}},
        }
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._last_id = 0
        
    async def load_markets(self) -> Dict[str, Any]:
        return self._mk
        
    async def fetch_ticker(self, gate_sym: str) -> Dict[str, Any]:
        return {"symbol": gate_sym, "last": 60000.0, "bid": 59990.0, "ask": 60010.0}
        
    async def fetch_balance(self) -> Dict[str, Any]:
        return {"BTC": {"free": 0.01}, "USDT": {"free": 1000}}
        
    async def create_order(
        self, 
        gate_sym: str, 
        typ: str, 
        side: str, 
        amount: float, 
        price: float | None,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._last_id += 1
        oid = f"{self._last_id}"
        self._orders[oid] = {"id": oid, "symbol": gate_sym, "type": typ, "side": side, "amount": amount}
        return self._orders[oid]
        
    async def fetch_order(self, oid: str, gate_sym: str) -> Dict[str, Any]:
        return self._orders.get(oid, {})


@pytest.mark.asyncio
async def test_ccxt_adapter_min_flow(mock_settings: Any) -> None:
    br = CcxtBroker(exchange=_FakeExchange(), settings=mock_settings)

    t = await br.fetch_ticker("BTC/USDT")
    assert t["symbol"].endswith("usdt")  # gate формат

    bal = await br.fetch_balance("BTC/USDT")
    assert dec(bal["free_quote"]) > 0

    order = await br.create_market_buy_quote(symbol="BTC/USDT", quote_amount=Decimal("10"))
    assert order["id"]