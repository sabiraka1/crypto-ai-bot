# src/crypto_ai_bot/core/application/use_cases/reconcile.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus  # fixed
from crypto_ai_bot.core.infrastructure.events import topics             # fixed
from crypto_ai_bot.core.infrastructure.storage.facade import Storage    # fixed


@dataclass
class ReconcileReport:
    ok: bool
    details: Dict[str, str]


async def reconcile_once(*, storage: Storage, bus: AsyncEventBus) -> ReconcileReport:
    """
    Лёгкая сверка «жив ли storage и шина событий».
    Реальная сверка ордеров/позиций/балансов вынесена в
    core/application/reconciliation/{orders,positions,balances}.py
    """
    details: Dict[str, str] = {}
    try:
        # простая проверка: доступ к базе
        _ = storage.health_ping()
        details["db"] = "ok"
    except Exception as exc:
        details["db"] = f"error:{exc}"

    try:
        await bus.publish(topics.SYSTEM_RECONCILE, {"ping": "pong"})
        details["bus"] = "ok"
    except Exception as exc:
        details["bus"] = f"error:{exc}"

    ok = all(v == "ok" for v in details.values())
    return ReconcileReport(ok=ok, details=details)
