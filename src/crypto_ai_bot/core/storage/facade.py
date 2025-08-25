from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .repositories.audit import AuditRepository
from .repositories.idempotency import IdempotencyRepository
from .repositories.positions import PositionsRepository


@dataclass
class Storage:
    conn: sqlite3.Connection
    audit: AuditRepository
    idempotency: IdempotencyRepository
    positions: PositionsRepository

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Storage":
        return cls(
            conn=conn,
            audit=AuditRepository(conn),
            idempotency=IdempotencyRepository(conn),
            positions=PositionsRepository(conn),
        )