from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str            # "buy" | "sell"
    amount: Decimal      # запрошенный объём (base для sell, вычисленный base для buy_quote)
    filled: Decimal      # исполненный объём (base)
    status: str          # "open" | "closed" | "canceled" | "failed" | "partial"
    timestamp: int

    # Расширения v2:
    price: Optional[Decimal] = None     # средняя цена fill
    cost: Optional[Decimal] = None      # израсходованный quote
    remaining: Optional[Decimal] = None # остаток base
    fee: Optional[Decimal] = None       # комиссия в fee_currency
    fee_currency: Optional[str] = None
