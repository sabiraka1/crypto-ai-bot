from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OrdersRepository:
    conn: Any  # sqlite3.Connection

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS orders ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " broker_order_id TEXT,"
            " client_order_id TEXT,"
            " symbol TEXT NOT NULL,"
            " side TEXT NOT NULL,"
            " amount TEXT NOT NULL,"
            " filled TEXT NOT NULL DEFAULT '0',"
            " status TEXT NOT NULL DEFAULT 'open',"
            " ts_ms INTEGER NOT NULL"
            ")"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self.conn.commit()

    # ---------- helpers ----------

    def _exists_by_broker_id(self, broker_order_id: str | None) -> bool:
        if not broker_order_id:
            return False
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM orders WHERE broker_order_id = ? LIMIT 1", (broker_order_id,))
        return cur.fetchone() is not None

    def _exists_by_client_id(self, client_order_id: str | None) -> bool:
        if not client_order_id:
            return False
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM orders WHERE client_order_id = ? LIMIT 1", (client_order_id,))
        return cur.fetchone() is not None

    # ---------- public API ----------

    def upsert_open(self, order: Any) -> None:
        """ДћвЂ™Г‘ВЃГ‘вЂљДћВ°ДћВІДћВ»Г‘ВЏДћВµГ‘вЂљ ДћВѕГ‘вЂљДћВєГ‘в‚¬Г‘вЂ№Г‘вЂљГ‘вЂ№ДћВ№ ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬, ДћВµГ‘ВЃДћВ»ДћВё Г‘вЂљДћВ°ДћВєДћВѕДћВіДћВѕ ДћВµГ‘вЂ°Г‘вЂ ДћВЅДћВµГ‘вЂљ (ДћВїДћВѕ broker_id ДћВёДћВ»ДћВё client_id)."""
        self.ensure_schema()
        broker_id = getattr(order, "id", None) or getattr(order, "order_id", None)
        client_id = getattr(order, "client_order_id", None)
        if self._exists_by_broker_id(broker_id) or self._exists_by_client_id(client_id):
            return
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO orders (broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                broker_id,
                client_id,
                getattr(order, "symbol", None),
                getattr(order, "side", None),
                str(getattr(order, "amount", "0")),
                str(getattr(order, "filled", "0")),
                getattr(order, "status", "open") or "open",
                int(getattr(order, "ts_ms", 0)),
            ),
        )
        self.conn.commit()

    def list_open(self, symbol: str) -> list[dict[str, Any]]:
        """ДћВћГ‘вЂљДћВєГ‘в‚¬Г‘вЂ№Г‘вЂљГ‘вЂ№ДћВµ (ДћВёДћВ»ДћВё Г‘вЂЎДћВ°Г‘ВЃГ‘вЂљДћВёГ‘вЂЎДћВЅДћВѕ ДћВёГ‘ВЃДћВїДћВѕДћВ»ДћВЅДћВµДћВЅДћВЅГ‘вЂ№ДћВµ) ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬ДћВ° ДћВїДћВѕ Г‘ВЃДћВёДћВјДћВІДћВѕДћВ»Г‘Ж’, Г‘ВЃГ‘вЂљДћВ°Г‘в‚¬Г‘вЂ№ДћВµ ГўвЂ вЂ™ ДћВЅДћВѕДћВІГ‘вЂ№ДћВµ."""
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms "
            "FROM orders WHERE symbol = ? AND status != 'closed' ORDER BY ts_ms ASC",
            (symbol,),
        )
        rows = cur.fetchall() or []
        result: list[dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                result.append(dict(r))
            else:
                result.append(
                    {
                        "id": r[0],
                        "broker_order_id": r[1],
                        "client_order_id": r[2],
                        "symbol": r[3],
                        "side": r[4],
                        "amount": r[5],
                        "filled": r[6],
                        "status": r[7],
                        "ts_ms": r[8],
                    }
                )
        return result

    def update_progress(self, broker_order_id: str, filled: str) -> None:
        """ДћВћДћВ±ДћВЅДћВѕДћВІДћВ»Г‘ВЏДћВµГ‘вЂљ filled, ДћВЅДћВµ ДћВјДћВµДћВЅГ‘ВЏГ‘ВЏ Г‘ВЃГ‘вЂљДћВ°Г‘вЂљГ‘Ж’Г‘ВЃ."""
        if not broker_order_id:
            return
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE orders SET filled=? WHERE broker_order_id=? AND status!='closed'",
            (str(filled), broker_order_id),
        )
        self.conn.commit()

    def mark_closed(self, broker_order_id: str, filled: str) -> None:
        """ДћЕёДћВѕДћВјДћВµГ‘вЂЎДћВ°ДћВµГ‘вЂљ ДћВѕГ‘в‚¬ДћВґДћВµГ‘в‚¬ ДћВ·ДћВ°ДћВєГ‘в‚¬Г‘вЂ№Г‘вЂљГ‘вЂ№ДћВј ДћВё Г‘вЂћДћВёДћВєГ‘ВЃДћВёГ‘в‚¬Г‘Ж’ДћВµГ‘вЂљ Г‘вЂћДћВёДћВЅДћВ°ДћВ»Г‘Е’ДћВЅГ‘вЂ№ДћВ№ filled."""
        if not broker_order_id:
            return
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE orders SET status='closed', filled=? WHERE broker_order_id=?",
            (str(filled), broker_order_id),
        )
        self.conn.commit()
