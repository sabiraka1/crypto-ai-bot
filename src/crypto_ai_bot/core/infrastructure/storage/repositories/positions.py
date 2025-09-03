from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec


# Константа для дефолтного значения B008
_DEFAULT_FEE_ZERO = dec("0")


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)

@dataclass
class Position:
    symbol: str
    base_qty: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    updated_ts_ms: int
    version: int

@dataclass
class PositionsRepository:
    conn: Any

    def __post_init__(self) -> None:
        try:
            self.ensure_schema()
        except Exception:
            pass

    def ensure_schema(self) -> None:
        """Создает таблицу positions если её нет."""
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                base_qty NUMERIC NOT NULL DEFAULT 0,
                avg_entry_price NUMERIC NOT NULL DEFAULT 0,
                realized_pnl NUMERIC NOT NULL DEFAULT 0,
                unrealized_pnl NUMERIC NOT NULL DEFAULT 0,
                updated_ts_ms INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0
            )
        """)
        self.conn.commit()

    def get_position(self, symbol: str) -> Position:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version FROM positions WHERE symbol = ?",
            (symbol,),
        )
        r = cur.fetchone()
        if not r:
            return Position(symbol=symbol, base_qty=dec("0"), avg_entry_price=dec("0"),
                            realized_pnl=dec("0"), unrealized_pnl=dec("0"),
                            updated_ts_ms=0, version=0)
        return Position(
            symbol=r["symbol"],
            base_qty=dec(str(r["base_qty"] or "0")),
            avg_entry_price=dec(str(r["avg_entry_price"] or "0")),
            realized_pnl=dec(str(r["realized_pnl"] or "0")),
            unrealized_pnl=dec(str(r["unrealized_pnl"] or "0")),
            updated_ts_ms=int(r["updated_ts_ms"] or 0),
            version=int(r["version"] or 0),
        )

    def get_base_qty(self, symbol: str) -> Decimal:
        return self.get_position(symbol).base_qty

    # 🔹 батч-доступ
    def get_positions_many(self, symbols: list[str]) -> dict[str, Position]:
        if not symbols:
            return {}
        placeholders = ",".join(["?"] * len(symbols))
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version FROM positions WHERE symbol IN ({placeholders})",
            symbols,
        )
        out: dict[str, Position] = {}
        for r in cur.fetchall():
            out[r["symbol"]] = Position(
                symbol=r["symbol"],
                base_qty=dec(str(r["base_qty"] or "0")),
                avg_entry_price=dec(str(r["avg_entry_price"] or "0")),
                realized_pnl=dec(str(r["realized_pnl"] or "0")),
                unrealized_pnl=dec(str(r["unrealized_pnl"] or "0")),
                updated_ts_ms=int(r["updated_ts_ms"] or 0),
                version=int(r["version"] or 0),
            )
        # добиваем отсутствующие дефолтами
        for s in symbols:
            if s not in out:
                out[s] = Position(symbol=s, base_qty=dec("0"), avg_entry_price=dec("0"),
                                  realized_pnl=dec("0"), unrealized_pnl=dec("0"),
                                  updated_ts_ms=0, version=0)
        return out

    def set_base_qty(self, symbol: str, value: Decimal) -> None:
        cur = self.conn.cursor()
        ts = _now_ms()
        cur.execute(
            """
            INSERT INTO positions (symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version)
            VALUES (?, ?, 0, 0, 0, ?, 0)
            ON CONFLICT(symbol) DO UPDATE SET base_qty=excluded.base_qty, updated_ts_ms=excluded.updated_ts_ms
            """,
            (symbol, str(value), ts),
        )
        self.conn.commit()

    def apply_trade(self, *, symbol: str, side: str, base_amount: Decimal,
                    price: Decimal, fee_quote: Decimal | None = None,
                    last_price: Decimal | None = None) -> None:
        # Обработка дефолтного значения для B008
        if fee_quote is None:
            fee_quote = _DEFAULT_FEE_ZERO

        side = (side or "").lower().strip()
        if side not in ("buy", "sell"):
            return

        pos = self.get_position(symbol)
        base0, avg0, realized0, ver0 = pos.base_qty, pos.avg_entry_price, pos.realized_pnl, pos.version

        if side == "buy":
            if base_amount <= 0:
                return
            new_base = base0 + base_amount
            new_avg = ((avg0 * base0) + (price * base_amount)) / new_base if new_base > 0 else dec("0")
            new_realized = realized0 - (fee_quote if fee_quote else dec("0"))
        else:
            if base_amount <= 0:
                return
            matched = base_amount if base_amount <= base0 else base0
            pnl = (price - avg0) * matched
            new_realized = realized0 + pnl - (fee_quote if fee_quote else dec("0"))
            new_base = base0 - base_amount
            new_avg = avg0 if new_base > 0 else dec("0")

        ref_price = (last_price if last_price is not None else price) or dec("0")
        new_unreal = (ref_price - new_avg) * new_base if (new_base > 0 and new_avg > 0 and ref_price > 0) else dec("0")

        cur = self.conn.cursor()
        ts = _now_ms()
        for _ in range(2):
            cur.execute(
                """
                INSERT INTO positions (symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(symbol) DO UPDATE SET
                    base_qty = ?,
                    avg_entry_price = ?,
                    realized_pnl = ?,
                    unrealized_pnl = ?,
                    updated_ts_ms = ?,
                    version = positions.version + 1
                WHERE positions.version = ?
                """,
                (
                    symbol, str(new_base), str(new_avg), str(new_realized), str(new_unreal), ts,
                    str(new_base), str(new_avg), str(new_realized), str(new_unreal), ts, ver0
                ),
            )
            self.conn.commit()
            if cur.rowcount > 0:
                return
            pos = self.get_position(symbol)
            base0, avg0, realized0, ver0 = pos.base_qty, pos.avg_entry_price, pos.realized_pnl, pos.version
            if side == "buy":
                new_base = base0 + base_amount
                new_avg = ((avg0 * base0) + (price * base_amount)) / new_base if new_base > 0 else dec("0")
                new_realized = realized0 - (fee_quote if fee_quote else dec("0"))
            else:
                matched = base_amount if base_amount <= base0 else base0
                pnl = (price - avg0) * matched
                new_realized = realized0 + pnl - (fee_quote if fee_quote else dec("0"))
                new_base = base0 - base_amount
                new_avg = avg0 if new_base > 0 else dec("0")
            new_unreal = (ref_price - new_avg) * new_base if (new_base > 0 and new_avg > 0 and ref_price > 0) else dec("0")
