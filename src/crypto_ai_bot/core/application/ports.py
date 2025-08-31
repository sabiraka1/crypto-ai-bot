from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SafetySwitchPort(Protocol):
    """
    Порт Dead Man's Switch: сервис обязан периодически вызывать ping()
    (например, раз в N секунд). Если пингов нет — внешняя система может
    остановить торги/закрыть позиции. В нашем коде допускается no-op.
    """
    async def start(self) -> None: ...
    async def ping(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class InstanceLockPort(Protocol):
    """
    Порт эксклюзивного лок-инстанса: чтобы не запустить два робота на один символ.
    """
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...


# ---- Безопасные заглушки (используются, когда DMS/LOCK выключены) ----

class NoopSafetySwitch(SafetySwitchPort):
    async def start(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class NoopInstanceLock(InstanceLockPort):
    async def acquire(self) -> bool:
        return True  # позволяем запуск (нет фактической блокировки)

    async def release(self) -> None:
        return None


__all__ = [
    "InstanceLockPort",
    "NoopInstanceLock",
    "NoopSafetySwitch",
    "SafetySwitchPort",
]
