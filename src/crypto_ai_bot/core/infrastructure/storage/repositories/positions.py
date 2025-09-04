from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterable

from crypto_ai_bot.utils.decimal import dec

# Constant for default B008 value
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

    # ---------- schema ----------
    def ensure_schema(self) -> None:
        """Создаёт таблицу positions, если её нет."""
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                base_qty NUMERIC NOT NULL DEFAULT 0,
                avg_entry_price NUMERIC NOT NULL DEFAULT 0,
                realized_pnl NUMERIC NOT NULL DEFAULT 0,
                unrealized_pnl NUMERIC NOT NULL DEFAULT 0,
                updated_ts_ms INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.commit()

    # ---------- getters ----------
    def get_position(self, symbol: str) -> Position:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version
            FROM positions WHERE symbol = ?
            """,
            (symbol,),
        )
        r = cur.fetchone()
        if not r:
            return Position(
                symbol=symbol,
                base_qty=dec("0"),
                avg_entry_price=dec("0"),
                realized_pnl=dec("0"),
                unrealized_pnl=dec("0"),
                updated_ts_ms=0,
                version=0,
            )
        if hasattr(r, "keys"):
            d = dict(r)  # type: ignore[arg-type]
            return Position(
                symbol=d["symbol"],
                base_qty=dec(str(d["base_qty"] or "0")),
                avg_entry_price=dec(str(d["avg_entry_price"] or "0")),
                realized_pnl=dec(str(d["realized_pnl"] or "0")),
                unrealized_pnl=dec(str(d["unrealized_pnl"] or "0")),
                updated_ts_ms=int(d["updated_ts_ms"] or 0),
                version=int(d["version"] or 0),
            )
        return Position(
            symbol=r[0],
            base_qty=dec(str(r[1] or "0")),
            avg_entry_price=dec(str(r[2] or "0")),
            realized_pnl=dec(str(r[3] or "0")),
            unrealized_pnl=dec(str(r[4] or "0")),
            updated_ts_ms=int(r[5] or 0),
            version=int(r[6] or 0),
        )

    def get_base_qty(self, symbol: str) -> Decimal:
        return self.get_position(symbol).base_qty

    def get_positions_many(self, symbols: list[str]) -> dict[str, Position]:
        """Пакетная выборка нескольких позиций."""
        if not symbols:
            return {}
        placeholders = ",".join(["?"] * len(symbols))
        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version
            FROM positions WHERE symbol IN ({placeholders})
            """,
            symbols,
        )
        out: dict[str, Position] = {}
        rows = cur.fetchall() or []
        for r in rows:
            if hasattr(r, "keys"):
                d = dict(r)  # type: ignore[arg-type]
                out[d["symbol"]] = Position(
                    symbol=d["symbol"],
                    base_qty=dec(str(d["base_qty"] or "0")),
                    avg_entry_price=dec(str(d["avg_entry_price"] or "0")),
                    realized_pnl=dec(str(d["realized_pnl"] or "0")),
                    unrealized_pnl=dec(str(d["unrealized_pnl"] or "0")),
                    updated_ts_ms=int(d["updated_ts_ms"] or 0),
                    version=int(d["version"] or 0),
                )
            else:
                out[r[0]] = Position(
                    symbol=r[0],
                    base_qty=dec(str(r[1] or "0")),
                    avg_entry_price=dec(str(r[2] or "0")),
                    realized_pnl=dec(str(r[3] or "0")),
                    unrealized_pnl=dec(str(r[4] or "0")),
                    updated_ts_ms=int(r[5] or 0),
                    version=int(r[6] or 0),
                )
        # добавляем отсутствующие с дефолтами
        for s in symbols:
            if s not in out:
                out[s] = Position(
                    symbol=s,
                    base_qty=dec("0"),
                    avg_entry_price=dec("0"),
                    realized_pnl=dec("0"),
                    unrealized_pnl=dec("0"),
                    updated_ts_ms=0,
                    version=0,
                )
        return out

    # ---------- setters / apply ----------
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

    def apply_trade(
        self,
        *,
        symbol: str,
        side: str,
        base_amount: Decimal,
        price: Decimal,
        fee_quote: Decimal | None = None,
        last_price: Decimal | None = None,
    ) -> None:
        """
        Обновляет позицию по символу.

        ⚠️ ВАЖНО: Реализованный PnL и остаток/средняя цена считаются по FIFO
        на основе фактических сделок из таблицы `trades`.
        Комиссия покупок капитализируется в цену лота (см. pnl.fifo_detail),
        комиссия продаж вычитается из realized.

        Если таблицы `trades` нет/ошибка — мягкий откат к «усреднённой» формуле (как раньше).
        """
        from importlib import import_module

        if fee_quote is None:
            fee_quote = _DEFAULT_FEE_ZERO

        side = (side or "").lower().strip()
        if side not in ("buy", "sell"):
            return

        # --- 1) Попытка FIFO по историческим сделкам из БД ---
        try:
            trades = list(self._load_trades_for_symbol(symbol))
            # fallback: если в БД нет сделок — считаем «как раньше»
            if trades:
                fifo_mod = None
                for mod_name in (
                    "crypto_ai_bot.core.domain.pnl",
                    "crypto_ai_bot.pnl",
                    "pnl",
                ):
                    try:
                        fifo_mod = import_module(mod_name)
                        break
                    except Exception:
                        continue
                if fifo_mod is None:
                    raise ImportError("pnl module not found")

                detail = fifo_mod.fifo_detail(trades)  # type: ignore[attr-defined]
                rem_base = detail.get("remaining_base", dec("0"))
                avg_entry = detail.get("avg_entry_price", dec("0"))
                realized = detail.get("realized_quote", dec("0"))

                # unrealized от last_price (если есть), иначе от price
                ref_price = last_price if last_price is not None else price
                unreal = (ref_price - avg_entry) * rem_base if (rem_base > 0 and avg_entry > 0 and ref_price > 0) else dec("0")

                self._upsert_position_fifo(
                    symbol=symbol,
                    base_qty=rem_base,
                    avg_entry=avg_entry,
                    realized=realized,
                    unrealized=unreal,
                )
                return
        except Exception:
            # fallback к прежней логике — не падаем
            pass

        # --- 2) Fallback: «усреднённая» формула (как было) ---
        pos = self.get_position(symbol)
        base0, avg0, realized0, ver0 = pos.base_qty, pos.avg_entry_price, pos.realized_pnl, pos.version

        if base_amount <= 0:
            return

        if side == "buy":
            new_base = base0 + base_amount
            new_avg = ((avg0 * base0) + (price * base_amount)) / new_base if new_base > 0 else dec("0")
            new_realized = realized0 - (fee_quote or dec("0"))
        else:
            matched = base_amount if base_amount <= base0 else base0
            pnl = (price - avg0) * matched
            new_realized = realized0 + pnl - (fee_quote or dec("0"))
            new_base = base0 - base_amount
            new_avg = avg0 if new_base > 0 else dec("0")

        ref_price = (last_price if last_price is not None else price) or dec("0")
        new_unreal = (ref_price - new_avg) * new_base if (new_base > 0 and new_avg > 0 and ref_price > 0) else dec("0")

        self._upsert_position_optimistic(
            symbol=symbol,
            base_qty=new_base,
            avg_entry=new_avg,
            realized=new_realized,
            unrealized=new_unreal,
            expected_version=ver0,
            ref_price=ref_price,
        )

    # ---------- internals ----------
    def _load_trades_for_symbol(self, symbol: str) -> Iterable[dict[str, Any]]:
        """
        Забираем сделки символа из таблицы `trades` (максимально совместимо с разными схемами).
        Ожидаемые поля: side, amount/base_amount/filled, price, cost, fee|fees|fee_quote, ts_ms.
        """
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                SELECT symbol, side, amount, filled, price, cost, fee_quote, ts_ms,
                       client_order_id, broker_order_id
                FROM trades
                WHERE symbol = ?
                ORDER BY COALESCE(ts_ms, 0) ASC, id ASC
                """,
                (symbol,),
            )
        except Exception:
            # если схема другая — пробуем минимальный набор
            cur.execute(
                """
                SELECT symbol, side, amount, price, ts_ms
                FROM trades
                WHERE symbol = ?
                ORDER BY COALESCE(ts_ms, 0) ASC
                """,
                (symbol,),
            )

        rows = cur.fetchall() or []
        out: list[dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                d = dict(r)  # type: ignore[arg-type]
            else:
                # совместимость с tuple — бежим по известным индексам
                d = {}
                try:
                    d["symbol"] = r[0]
                    d["side"] = r[1]
                    d["amount"] = r[2]
                    d["price"] = r[4] if len(r) > 4 else r[2]
                    d["ts_ms"] = r[7] if len(r) > 7 else (r[4] if len(r) > 4 else None)
                except Exception:
                    pass
            out.append(d)
        return out

    def _upsert_position_fifo(
        self,
        *,
        symbol: str,
        base_qty: Decimal,
        avg_entry: Decimal,
        realized: Decimal,
        unrealized: Decimal,
    ) -> None:
        ts = _now_ms()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO positions (symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms, version)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(symbol) DO UPDATE SET
                base_qty = excluded.base_qty,
                avg_entry_price = excluded.avg_entry_price,
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                updated_ts_ms = excluded.updated_ts_ms,
                version = positions.version + 1
            """,
            (symbol, str(base_qty), str(avg_entry), str(realized), str(unrealized), ts),
        )
        self.conn.commit()

    def _upsert_position_optimistic(
        self,
        *,
        symbol: str,
        base_qty: Decimal,
        avg_entry: Decimal,
        realized: Decimal,
        unrealized: Decimal,
        expected_version: int,
        ref_price: Decimal,
    ) -> None:
        """
        Прежняя «усреднённая» ветка — оставлена как fallback.
        """
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
                    symbol,
                    str(base_qty),
                    str(avg_entry),
                    str(realized),
                    str(unrealized),
                    ts,
                    str(base_qty),
                    str(avg_entry),
                    str(realized),
                    str(unrealized),
                    ts,
                    expected_version,
                ),
            )
            self.conn.commit()
            if cur.rowcount > 0:
                return
            # конфликт версии — перечитываем и пробуем один раз ещё
            pos = self.get_position(symbol)
            expected_version = pos.version
