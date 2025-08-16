from __future__ import annotations

"""
Простой PaperExchange для тестов/pepper-trading.
- Нормализует symbol/timeframe во всех входах
- Интерфейс совместим с ExchangeInterface
- Детерминированная генерация OHLCV для стабильных тестов
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Tuple
import math
import random

from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe, to_exchange_symbol


@dataclass
class PaperExchange:
    mode: str = "paper"
    seed: int = 42
    price_map: Dict[str, float] = field(default_factory=dict)

    def _rng(self, key: str) -> random.Random:
        # детерминированный генератор на основе ключа + seed
        return random.Random(hash((self.seed, key)) & 0xFFFFFFFF)

    # --- helpers ---
    def _tf_seconds(self, tf: str) -> int:
        # простая конвертация
        tf = tf.lower()
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400
        return 3600

    # --- protocol methods ---
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        sym = normalize_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        secs = self._tf_seconds(tf)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(seconds=secs * (limit))
        rr = self._rng(f"ohlcv:{sym}:{tf}:{limit}:{start.isoformat()}")
        base = self.price_map.get(sym, 50000.0)
        out: List[List[float]] = []
        t = start
        price = base
        for i in range(limit):
            t = t + timedelta(seconds=secs)
            # синтетика: плавный тренд + небольшой шум
            angle = i / max(1, limit) * math.pi * 2
            drift = math.sin(angle) * (base * 0.005)
            noise = rr.uniform(-base * 0.001, base * 0.001)
            close = max(1.0, base + drift + noise)
            high = close * (1 + rr.uniform(0, 0.003))
            low = close * (1 - rr.uniform(0, 0.003))
            open_ = (price + close) / 2
            vol = abs(rr.gauss(10.0, 2.0))
            out.append([int(t.timestamp() * 1000), float(open_), float(high), float(low), float(close), float(vol)])
            price = close
        # последнюю цену положим в карту
        self.price_map[sym] = price
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        last = self.price_map.get(sym, 50000.0)
        return {"symbol": to_exchange_symbol(sym), "last": float(last), "close": float(last), "bid": float(last*0.999), "ask": float(last*1.001)}

    def create_order(self, symbol: str, type_: str, side: str, amount: Decimal, price: Decimal | None = None) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        # рыночное исполнение по текущему last
        tkr = self.fetch_ticker(sym)
        last = Decimal(str(tkr.get("last", "0")))
        order_id = f"paper-{sym}-{side}-{int(datetime.now(timezone.utc).timestamp())}"
        filled = amount
        exec_price = last if price is None else Decimal(price)
        return {"id": order_id, "symbol": to_exchange_symbol(sym), "type": type_, "side": side, "amount": str(amount), "price": float(exec_price), "filled": str(filled), "status": "closed"}

    def fetch_balance(self) -> Dict[str, Any]:
        # статичный баланс для тестов
        return {"free": {"USDT": 100000.0}, "used": {}, "total": {"USDT": 100000.0}}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {"id": order_id, "status": "canceled"}

    # stats for metrics (optional)
    def get_stats(self) -> Dict[str, Any]:
        return {}
