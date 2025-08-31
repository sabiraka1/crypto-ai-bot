from __future__ import annotations

from dataclasses import dataclass

from .ccxt_adapter import CcxtBroker


@dataclass
class LiveBroker(CcxtBroker):
    """Тонкая обёртка для явного live режима."""

    def __post_init__(self) -> None:
        self.dry_run = False  # Всегда false для live
        super().__post_init__()
