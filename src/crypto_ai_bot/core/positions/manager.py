from __future__ import annotations
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.storage.interfaces import PositionRepository, TradeRepository, AuditRepository, UnitOfWork

@dataclass
class PositionManager:
    positions_repo: PositionRepository
    trades_repo: TradeRepository
    audit_repo: AuditRepository
    uow: UnitOfWork

    def _now(self) -> int:
        return int(time.time() * 1000)

    def open_or_add(self, symbol: str, delta_size: Decimal, price: Optional[Decimal]) -> Dict[str, Any]:
        if delta_size == 0:
            return self.get_snapshot(symbol)

        pos = self.positions_repo.get_by_symbol(symbol)
        if pos is None:
            if price is None:
                raise ValueError("price is required for opening a new position")
            self.uow.begin()
            try:
                self.positions_repo.save(symbol, delta_size, price)
                self.trades_repo.insert({
                    "ts": self._now(),
                    "symbol": symbol,
                    "side": "buy" if delta_size > 0 else "sell",
                    "size": str(abs(delta_size)),
                    "price": str(price),
                    "meta": {"reason": "open_or_add:new"},
                })
                self.audit_repo.log("position_opened", {"symbol": symbol, "size": str(delta_size), "price": str(price)})
                self.uow.commit()
            except Exception:
                self.uow.rollback()
                raise
            return self.get_snapshot(symbol)

        cur_size: Decimal = pos["size"]
        cur_avg: Decimal = pos["avg_price"]
        new_size = cur_size + delta_size

        if new_size == 0:
            px = price if price is not None else cur_avg
            self.uow.begin()
            try:
                self.positions_repo.save(symbol, Decimal("0"), cur_avg)
                self.trades_repo.insert({
                    "ts": self._now(),
                    "symbol": symbol,
                    "side": "sell" if cur_size > 0 else "buy",
                    "size": str(abs(delta_size)),
                    "price": str(px),
                    "meta": {"reason": "open_or_add:close"},
                })
                self.audit_repo.log("position_closed", {"symbol": symbol, "close_size": str(delta_size), "price": str(px)})
                self.uow.commit()
            except Exception:
                self.uow.rollback()
                raise
            return self.get_snapshot(symbol)

        px = price if price is not None else cur_avg
        if (cur_size > 0 and new_size > 0) or (cur_size < 0 and new_size < 0):
            new_avg = ((cur_size * cur_avg) + (delta_size * px)) / new_size
        else:
            new_avg = px

        self.uow.begin()
        try:
            self.positions_repo.save(symbol, new_size, new_avg)
            self.trades_repo.insert({
                "ts": self._now(),
                "symbol": symbol,
                "side": "buy" if delta_size > 0 else "sell",
                "size": str(abs(delta_size)),
                "price": str(px),
                "meta": {"reason": "open_or_add:adjust"},
            })
            self.audit_repo.log("position_adjusted", {
                "symbol": symbol,
                "delta": str(delta_size),
                "price": str(px),
                "new_size": str(new_size),
                "new_avg": str(new_avg),
            })
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise

        return self.get_snapshot(symbol)

    def close_all(self, symbol: str) -> Dict[str, Any]:
        pos = self.positions_repo.get_by_symbol(symbol)
        if not pos or pos["size"] == 0:
            return {"symbol": symbol, "size": "0", "avg_price": "0"}
        close_size = -pos["size"]
        px = pos["avg_price"]
        self.uow.begin()
        try:
            self.positions_repo.save(symbol, Decimal("0"), pos["avg_price"])
            self.trades_repo.insert({
                "ts": self._now(),
                "symbol": symbol,
                "side": "sell" if close_size < 0 else "buy",
                "size": str(abs(close_size)),
                "price": str(px),
                "meta": {"reason": "close_all"},
            })
            self.audit_repo.log("position_closed", {"symbol": symbol, "close_size": str(close_size), "price": str(px)})
            self.uow.commit()
        except Exception:
            self.uow.rollback()
            raise
        return self.get_snapshot(symbol)

    def get_snapshot(self, symbol: str) -> Dict[str, Any]:
        pos = self.positions_repo.get_by_symbol(symbol)
        if not pos:
            return {"symbol": symbol, "size": "0", "avg_price": "0"}
        return {
            "symbol": symbol,
            "size": str(pos["size"]),
            "avg_price": str(pos["avg_price"]),
            "updated_at": pos["updated_at"],
        }
