from __future__ import annotations
from typing import Literal, Dict, Any, Tuple, Protocol

Decision = Literal["buy", "sell", "hold"]

class IStrategy(Protocol):
    name: str
    def decide(self, symbol: str, feat: Dict[str, Any], *, cfg: Any) -> Tuple[Decision, Dict[str, Any]]: ...
