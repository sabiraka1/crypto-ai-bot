from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CorrelationConfig:
    groups: list[list[str]]  # [["BTC/USDT","ETH/USDT"], ["XRP/USDT","ADA/USDT"]]


class CorrelationManager:
    def __init__(self, cfg: CorrelationConfig) -> None:
        self.cfg = cfg

    def _open_symbols(self, positions_repo: Any) -> set[str]:
        # ДћВїГ‘в‚¬ДћВѕДћВ±Г‘Ж’ДћВµДћВј Г‘Ж’ДћВЅДћВёДћВІДћВµГ‘в‚¬Г‘ВЃДћВ°ДћВ»Г‘Е’ДћВЅДћВѕ: list_open() -> items Г‘ВЃ ДћВїДћВѕДћВ»ДћВµДћВј symbol
        try:
            items = None
            if hasattr(positions_repo, "list_open"):
                items = positions_repo.list_open()
            elif hasattr(positions_repo, "list"):
                items = [p for p in positions_repo.list() if getattr(p, "qty", 0) or getattr(p, "size", 0)]
            if not items:
                return set()
            out = set()
            for it in items:
                sym = getattr(it, "symbol", None) if not isinstance(it, dict) else it.get("symbol")
                if sym:
                    out.add(str(sym))
            return out
        except Exception:
            return set()

    def check(self, *, symbol: str, positions_repo: Any) -> tuple[bool, str, dict]:
        if not self.cfg.groups:
            return True, "disabled", {}
        open_syms = self._open_symbols(positions_repo)
        if not open_syms:
            return True, "no_positions", {}
        for group in self.cfg.groups:
            if symbol in group and any((s in open_syms) for s in group if s != symbol):
                return False, "anti_correlation", {"group": group, "open": list(open_syms)}
        return True, "ok", {}
