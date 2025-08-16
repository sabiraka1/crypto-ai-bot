# src/crypto_ai_bot/core/storage/repositories/audit.py
from __future__ import annotations
import json
from typing import Any, Dict
import sqlite3

from crypto_ai_bot.core.storage.interfaces import AuditRepository


class SqliteAuditRepository(AuditRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def record(self, event: Dict[str, Any]) -> None:
        payload = {k: v for k, v in event.items() if k not in {"type", "symbol", "side", "amount", "price", "fee", "client_order_id", "ts"}}
        self._con.execute(
            """
            INSERT INTO audit(type, symbol, side, amount, price, fee, client_order_id, ts, payload_json)
            VALUES(:type, :symbol, :side, :amount, :price, :fee, :client_order_id, :ts, :payload_json)
            """,
            {
                "type": event.get("type"),
                "symbol": event.get("symbol"),
                "side": event.get("side"),
                "amount": event.get("amount"),
                "price": event.get("price"),
                "fee": event.get("fee"),
                "client_order_id": event.get("client_order_id"),
                "ts": int(event.get("ts") or 0),
                "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        )
