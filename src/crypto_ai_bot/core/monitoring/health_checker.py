from __future__ import annotations
import sys
import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from crypto_ai_bot.utils.time import check_sync
from crypto_ai_bot.utils.logging import get_logger


@dataclass(slots=True)
class ProbeSection:
    ok: bool
    details: dict[str, Any] | None = None
    error: str | None = None


class HealthChecker:
    """Агрегированные проверки состояния системы.
    Разделяет *liveness* (процесс жив) и *readiness* (готовность зависимостей).
    Не тянет лишние зависимости и не создаёт реализации — работает на фундаменте.
    """

    def __init__(
        self,
        *,
        settings: Any,
        db_conn: Any | None,
        bus: Any | None,
        broker: Any | None = None,
        breakers: Optional[Sequence[Any]] = None,
        drift_warn_ms: int = 2500,
        drift_fail_ms: int = 5000,
    ) -> None:
        self._log = get_logger("health")
        self.settings = settings
        self.db = db_conn
        self.bus = bus
        self.broker = broker
        self.breakers = list(breakers) if breakers else []
        self.drift_warn_ms = int(drift_warn_ms)
        self.drift_fail_ms = int(drift_fail_ms)

    def liveness(self) -> dict[str, Any]:
        """Простая проверка: процесс жив, интерпретатор доступен."""
        return {
            "ok": True,
            "python": sys.version.split()[0],
            "mode": getattr(self.settings, "MODE", "paper"),
        }

    async def readiness(self) -> dict[str, Any]:
        sections: dict[str, ProbeSection] = {}

        # --- DB ---
        sections["db"] = self._check_db()

        # --- Event Bus ---
        sections["bus"] = self._check_bus()

        # --- Time Drift (optional, если брокер доступен) ---
        sections["time_drift"] = await self._check_time_drift()

        # --- Circuit Breakers (optional) ---
        sections["breakers"] = self._check_breakers()

        # Суммарный статус
        # ok, если все обязательные секции (db, bus) ok и нет fail по drift/breakers
        def status_of(section: ProbeSection) -> str:
            if not section.ok:
                return "fail"
            return "ok"

        mandatory = ("db", "bus")
        overall_ok = all(sections[name].ok for name in mandatory)
        any_fail = any(status_of(s) == "fail" for s in sections.values())
        status = "ok" if overall_ok and not any_fail else "degraded" if overall_ok else "fail"

        return {
            "status": status,
            "sections": {k: (vars(v) if hasattr(v, "__dict__") else v) for k, v in sections.items()},
        }

    # --- checks ---
    def _check_db(self) -> ProbeSection:
        if self.db is None:
            return ProbeSection(ok=False, error="db: not connected")
        try:
            cur = self.db.cursor()
            cur.execute("SELECT 1;")
            cur.fetchone()
            cur.close()
            return ProbeSection(ok=True)
        except Exception as e:  # noqa: BLE001
            return ProbeSection(ok=False, error=f"db error: {e}")

    def _check_bus(self) -> ProbeSection:
        if self.bus is None:
            return ProbeSection(ok=False, error="bus: not initialized")
        # Минимальный критерий: объект существует и не закрыт (duck-typing _closed)
        closed = getattr(self.bus, "_closed", False)
        return ProbeSection(ok=not closed, details={"closed": bool(closed)})

    async def _check_time_drift(self) -> ProbeSection:
        if self.broker is None:
            return ProbeSection(ok=True, details={"skipped": True})
        try:
            drift = abs(await check_sync(self.broker))
            state = "ok"
            if drift >= self.drift_fail_ms:
                state = "fail"
            elif drift >= self.drift_warn_ms:
                state = "warn"
            return ProbeSection(ok=state != "fail", details={"drift_ms": drift, "state": state})
        except Exception as e:  # noqa: BLE001
            return ProbeSection(ok=False, error=f"time drift check error: {e}")

    def _check_breakers(self) -> ProbeSection:
        if not self.breakers:
            return ProbeSection(ok=True, details={"count": 0})
        try:
            states = []
            any_open = False
            for i, br in enumerate(self.breakers):
                state = getattr(br, "state", "unknown")
                states.append({"index": i, "state": state})
                any_open = any_open or (state == "open")
            return ProbeSection(ok=not any_open, details={"states": states})
        except Exception as e:  # noqa: BLE001
            return ProbeSection(ok=False, error=f"breakers check error: {e}")
