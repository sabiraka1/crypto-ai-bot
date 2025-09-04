from __future__ import annotations

from decimal import Decimal
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("application.reconcile.positions")


# --- Centralized NO_SHORTS helper ---
def compute_sell_amount(storage: StoragePort, symbol: str, requested: Decimal | None) -> tuple[bool, Decimal]:
    """
    Единая проверка NO_SHORTS: ограничиваем объём продажи фактической позицией по базовой валюте.
    Возвращает (allowed, amount_to_sell). Если позиции нет → (False, 0).
    """
    try:
        repo = getattr(storage, "positions", None)
        if repo is None:
            return (False, dec("0"))

        pos = repo.get_position(symbol)

        # Извлекаем объём базовой валюты (поддержка как объектной, так и dict-структуры)
        held_raw = None
        if pos is not None:
            held_raw = getattr(pos, "base_qty", None)
            if held_raw is None and isinstance(pos, dict):
                held_raw = pos.get("base_qty")

        held = dec(str(held_raw or "0"))
        if held <= dec("0"):
            return (False, dec("0"))

        # Берём запрошенное значение или продаём всю позицию
        amt = dec(str(requested)) if requested is not None else held
        if amt > held:
            amt = held

        return (True, amt) if amt > dec("0") else (False, dec("0"))
    except Exception:
        _log.exception("compute_sell_amount_failed", extra={"symbol": symbol}, exc_info=True)
        return (False, dec("0"))


# Backward-compat shim
class PositionGuard:
    """Совместимый враппер для старого кода — единая точка проверки NO_SHORTS."""

    @staticmethod
    def can_sell(storage: StoragePort, symbol: str, amount: Decimal) -> tuple[bool, Decimal]:
        return compute_sell_amount(storage, symbol, amount)


# --- Reconciliation logic ---
async def reconcile_positions_batch(
    *, symbols: list[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort
) -> None:
    """
    Пересчитывает маркеры нереализованной прибыли/убытка, обновляя последнюю цену.
    Локально «трогаем» позицию через apply_trade с last_price, не изменяя количество.
    """
    for sym in symbols:
        try:
            ticker = await broker.fetch_ticker(sym)
            last = dec(str(ticker.get("last") or ticker.get("bid") or ticker.get("ask") or "0"))
            if last <= 0:
                _log.debug("reconcile_skip_no_price", extra={"symbol": sym})
                continue

            pos = storage.positions.get_position(sym)
            if not pos:
                _log.debug("reconcile_skip_no_position", extra={"symbol": sym})
                continue

            base = getattr(pos, "base_qty", dec("0")) or dec("0")
            if base <= 0:
                _log.debug("reconcile_skip_no_base", extra={"symbol": sym})
                continue

            avg = getattr(pos, "avg_entry_price", dec("0")) or dec("0")
            if avg <= 0:
                _log.debug("reconcile_skip_no_entry", extra={"symbol": sym})
                continue

            unreal = (last - avg) * base

            # Обновляем last_price в локальном кеше для корректного расчёта PnL (без изменения количества)
            storage.positions.apply_trade(
                symbol=sym,
                side="buy",
                base_amount=dec("0"),
                price=last,
                fee_quote=dec("0"),
                last_price=last,
            )
            _log.debug("reconcile_ok", extra={"symbol": sym, "unrealized": str(unreal)})
        except Exception as exc:
            _log.warning("reconcile_error", extra={"symbol": sym, "error": str(exc)}, exc_info=True)


# Orchestrator wrapper
async def reconcile_positions(
    symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, _settings: Any
) -> None:
    """Совместимый враппер для оркестратора: сверяем только указанный символ."""
    await reconcile_positions_batch(symbols=[symbol], storage=storage, broker=broker, bus=bus)
