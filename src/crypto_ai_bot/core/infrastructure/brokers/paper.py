from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

# РџРѕСЂС‚: С‚РѕР»СЊРєРѕ РёРјРїРѕСЂС‚ (РєРѕРЅС‚СЂР°РєС‚), СЂРµР°Р»РёР·Р°С†РёСЏ вЂ” РЅРёР¶Рµ РІ Р°РґР°РїС‚РµСЂРµ
from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("brokers.paper")


@dataclass
class PaperBroker:
    """РЎРёРјСѓР»СЏС‚РѕСЂ Р±СЂРѕРєРµСЂР° РґР»СЏ paper trading."""

    settings: Any

    def __post_init__(self) -> None:
        # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј Р°С‚СЂРёР±СѓС‚С‹ РїРѕСЃР»Рµ СЃРѕР·РґР°РЅРёСЏ (РѕСЃС‚Р°РІР»РµРЅРѕ РєР°Рє РµСЃС‚СЊ)
        self._balances: dict[str, Decimal] = {"USDT": dec("10000"), "BTC": dec("0.5")}
        self._positions: dict[str, Decimal] = {}
        self._orders: dict[str, Any] = {}
        self._last_prices: dict[str, Decimal] = defaultdict(lambda: dec("50000"))
        self.exchange = getattr(self.settings, "EXCHANGE", "paper") if self.settings else "paper"

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ С„РёРєС‚РёРІРЅС‹Р№ ticker."""
        price = self._last_prices[symbol]
        spread = price * dec("0.0002")  # 0.02% СЃРїСЂРµРґ
        return {
            "symbol": symbol,
            "bid": str(price - spread),
            "ask": str(price + spread),
            "last": str(price),
            "timestamp": now_ms(),
        }

    async def fetch_balance(self, symbol: str = "") -> dict[str, Any]:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ С„РёРєС‚РёРІРЅС‹Р№ Р±Р°Р»Р°РЅСЃ."""
        result = {}
        for asset, amount in self._balances.items():
            result[asset] = {"free": str(amount), "used": "0", "total": str(amount)}
        return result

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[list[float]]:
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ С„РёРєС‚РёРІРЅС‹Рµ OHLCV РґР°РЅРЅС‹Рµ."""
        price = float(self._last_prices[symbol])
        ohlcv: list[list[float]] = []
        ts = now_ms()
        for i in range(limit):
            # РЎРёРјСѓР»РёСЂСѓРµРј РЅРµР±РѕР»СЊС€РёРµ РєРѕР»РµР±Р°РЅРёСЏ С†РµРЅС‹
            variation = 0.995 + (i % 10) * 0.001
            p = price * variation
            ohlcv.append(
                [
                    float(ts - (limit - i) * 60000),  # timestamp
                    p * 0.999,  # open
                    p * 1.001,  # high
                    p * 0.998,  # low
                    p,  # close
                    100.0,  # volume
                ]
            )
        return ohlcv

    async def create_market_buy_quote(
        self,
        symbol: str,
        quote_amount: Decimal,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """РЎРёРјСѓР»РёСЂСѓРµС‚ РїРѕРєСѓРїРєСѓ (РєР°Рє Р±С‹Р»Рѕ)."""
        price = self._last_prices[symbol]
        amount = quote_amount / price
        fee = quote_amount * dec("0.001")

        # РћР±РЅРѕРІР»СЏРµРј Р±Р°Р»Р°РЅСЃС‹
        base, quote = symbol.split("/")
        if quote in self._balances:
            self._balances[quote] -= quote_amount + fee
        if base not in self._balances:
            self._balances[base] = dec("0")
        self._balances[base] = self._balances[base] + amount

        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "client_order_id": client_order_id,  # РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
            "symbol": symbol,
            "side": "buy",
            "type": "market",
            "amount": str(amount),
            "filled": str(amount),
            "remaining": "0",
            "price": str(price),
            "cost": str(quote_amount),
            "fee": {"currency": quote, "cost": str(fee)},
            "fee_quote": str(fee),
            "status": "closed",
            "timestamp": now_ms(),
            "ts_ms": now_ms(),
        }
        if client_order_id:
            self._orders[client_order_id] = order
        return order

    async def create_market_sell_base(
        self,
        symbol: str,
        base_amount: Decimal,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """РЎРёРјСѓР»РёСЂСѓРµС‚ РїСЂРѕРґР°Р¶Сѓ (РєР°Рє Р±С‹Р»Рѕ)."""
        price = self._last_prices[symbol]
        cost = base_amount * price
        fee = cost * dec("0.001")

        # РћР±РЅРѕРІР»СЏРµРј Р±Р°Р»Р°РЅСЃС‹
        base, quote = symbol.split("/")
        if base in self._balances:
            self._balances[base] -= base_amount
        if quote not in self._balances:
            self._balances[quote] = dec("0")
        self._balances[quote] = self._balances[quote] + (cost - fee)

        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "client_order_id": client_order_id,  # РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
            "symbol": symbol,
            "side": "sell",
            "type": "market",
            "amount": str(base_amount),
            "filled": str(base_amount),
            "remaining": "0",
            "price": str(price),
            "cost": str(cost),
            "fee": {"currency": quote, "cost": str(fee)},
            "fee_quote": str(fee),
            "status": "closed",
            "timestamp": now_ms(),
            "ts_ms": now_ms(),
        }
        if client_order_id:
            self._orders[client_order_id] = order
        return order

    async def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """РџРѕР»СѓС‡РёС‚СЊ РѕСЂРґРµСЂ РїРѕ ID."""
        default_order: dict[str, Any] = {
            "id": order_id,
            "symbol": symbol,
            "status": "closed",
            "filled": "0",
            "remaining": "0",
        }
        result: dict[str, Any] = self._orders.get(order_id, default_order)
        return result

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Р’ paper СЂРµР¶РёРјРµ РІСЃРµ РѕСЂРґРµСЂР° СЃСЂР°Р·Сѓ РёСЃРїРѕР»РЅСЏСЋС‚СЃСЏ, РїРѕСЌС‚РѕРјСѓ РѕС‚РєСЂС‹С‚С‹С… РЅРµС‚."""
        return []

    async def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Р’ paper СЂРµР¶РёРјРµ РЅРµС‡РµРіРѕ РѕС‚РјРµРЅСЏС‚СЊ."""
        return {"id": order_id, "status": "canceled"}


# -------------------------------
# РўРћРќРљРР™ РџРћР Рў-РђР”РђРџРўР•Р  (Р±РµР· СЃРјРµРЅС‹ Р»РѕРіРёРєРё)
# -------------------------------
class PaperBrokerPortAdapter(BrokerPort):
    """
    Р РµР°Р»РёР·Р°С†РёСЏ BrokerPort РїРѕРІРµСЂС… С‚РµРєСѓС‰РµРіРѕ PaperBroker.
    РќРёС‡РµРіРѕ РІ Р»РѕРіРёРєРµ РЅРµ РјРµРЅСЏРµРј вЂ” С‚РѕР»СЊРєРѕ В«РїРµСЂРµРІРѕРґРёРјВ» РІС‹Р·РѕРІС‹ РІ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРµ РјРµС‚РѕРґС‹.
    """

    def __init__(self, core: PaperBroker) -> None:
        self._core = core

    async def place_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quote_amount: Decimal,
        *,
        time_in_force: str = "GTC",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        # BUY: РµСЃС‚СЊ РїСЂСЏРјРѕР№ РјРµС‚РѕРґ В«РїРѕРєСѓРїРєР° РЅР° СЃСѓРјРјСѓ quoteВ»
        if side == "buy":
            return await self._core.create_market_buy_quote(
                symbol=symbol,
                quote_amount=quote_amount,
                client_order_id=idempotency_key,
            )
        # SELL: Сѓ core РјРµС‚РѕРґ В«РїСЂРѕРґР°Р¶Р° baseВ». РџРµСЂРµСЃС‡РёС‚С‹РІР°РµРј base = quote/price (РїРѕ С‚РµРєСѓС‰РµР№ last).
        # Р­С‚Рѕ СЂРѕРІРЅРѕ С‚Р° Р¶Рµ С„РѕСЂРјСѓР»Р°, С‡С‚Рѕ СѓР¶Рµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІ create_market_buy_quote.
        ticker = await self._core.fetch_ticker(symbol)
        price = dec(ticker["last"])
        if price <= 0:
            raise ValueError("Invalid price from ticker for sell")
        base_amount = quote_amount / price
        return await self._core.create_market_sell_base(
            symbol=symbol,
            base_amount=base_amount,
            client_order_id=idempotency_key,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        return await self._core.cancel_order(order_id=order_id, symbol=symbol)

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return await self._core.fetch_open_orders(symbol)

    async def fetch_order(self, symbol: str, order_id: str) -> dict[str, Any] | None:
        return await self._core.fetch_order(order_id=order_id, symbol=symbol)

    async def get_balance(self) -> dict[str, Any]:
        return await self._core.fetch_balance()
