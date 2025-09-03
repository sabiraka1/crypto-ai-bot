from __future__ import annotations

from dataclasses import dataclass

from .ccxt_adapter import CcxtBroker


@dataclass
class LiveBroker(CcxtBroker):
    """ДћВўДћВѕДћВЅДћВєДћВ°Г‘ВЏ ДћВѕДћВ±Г‘вЂГ‘в‚¬Г‘вЂљДћВєДћВ° ДћВґДћВ»Г‘ВЏ Г‘ВЏДћВІДћВЅДћВѕДћВіДћВѕ live Г‘в‚¬ДћВµДћВ¶ДћВёДћВјДћВ°."""

    def __post_init__(self) -> None:
        self.dry_run = False  # ДћвЂ™Г‘ВЃДћВµДћВіДћВґДћВ° false ДћВґДћВ»Г‘ВЏ live
        super().__post_init__()
