# src/crypto_ai_bot/app/maintenance.py
from __future__ import annotations

import asyncio
from typing import Any
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

async def maintenance_loop(container: Any, interval_sec: int = 300) -> None:
    """
    Единый неблокирующий цикл обслуживания:
    - очистка устаревших ключей идемпотентности
    - при необходимости: VACUUM/ANALYZE/backup (вынесите в отдельные вызовы)
    """
    repos = getattr(container, "repos", None)
    idem = getattr(repos, "idempotency", None) if repos else None

    while True:
        try:
            # безопасная проверка наличия метода
            if idem and hasattr(idem, "cleanup_expired"):
                expired = idem.cleanup_expired()
                logger.info("idempotency.cleanup_expired", extra={"expired": expired})
            else:
                logger.debug("idempotency repo not available — skip cleanup")
        except Exception as e:
            logger.exception("maintenance_loop error: %s", e)
        finally:
            await asyncio.sleep(interval_sec)
