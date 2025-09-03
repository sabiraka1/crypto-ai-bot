from __future__ import annotations

from dataclasses import dataclass

from .ccxt_adapter import CcxtBroker


@dataclass
class LiveBroker(CcxtBroker):
    """Ğ¢Ğ¾Ğ½ĞºĞ°Ñ Ğ¾Ğ±Ñ‘Ñ€Ñ‚ĞºĞ° Ğ´Ğ»Ñ ÑĞ²Ğ½Ğ¾Ğ³Ğ¾ live Ñ€ĞµĞ¶Ğ¸Ğ¼Ğ°."""

    def __post_init__(self) -> None:
        self.dry_run = False  # Ğ’ÑĞµĞ³Ğ´Ğ° false Ğ´Ğ»Ñ live
        super().__post_init__()
