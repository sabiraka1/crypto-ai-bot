from __future__ import annotations

from dataclasses import dataclass

from crypto_ai_bot.core.application.ports import BrokerPort


@dataclass
class OrdersReconciler:
    broker: BrokerPort
    symbol: str

    async def run_once(self) -> None:
        # Ğ’ Ğ±Ğ°Ğ·Ğ¾Ğ²Ğ¾Ğ¹ Ğ²ĞµÑ€ÑĞ¸Ğ¸ Ğ½Ğ¸Ñ‡ĞµĞ³Ğ¾ Ğ½Ğµ Ñ‚ÑĞ½ĞµĞ¼ Ğ¸Ğ· infrastructure Ğ½Ğ°Ğ¿Ñ€ÑĞ¼ÑƒÑ.
        # ĞÑÑ‚Ğ°Ğ²Ğ»ÑĞµĞ¼ Ğ·Ğ°Ğ³Ğ»ÑƒÑˆĞºÑƒ Ğ´Ğ»Ñ Ğ¿Ğ¾ÑĞ»ĞµĞ´ÑƒÑÑ‰Ğ¸Ñ… Ñ€Ğ°ÑÑˆĞ¸Ñ€ĞµĞ½Ğ¸Ğ¹ (ÑĞ²ĞµÑ€ĞºĞ° ÑÑ‚Ğ°Ñ‚ÑƒÑĞ¾Ğ² Ğ¾Ñ€Ğ´ĞµÑ€Ğ¾Ğ² Ğ¿Ğ¾ Ğ±Ğ¸Ñ€Ğ¶Ğµ)
        return None
