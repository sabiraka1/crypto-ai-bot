from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Mapping

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.application.events_topics import POSITIONS_UPDATED, RECONCILIATION_COMPLETED
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import trace_context

_log = get_logger("reconcile.positions")


def compute_sell_amount(storage: StoragePort, symbol: str, requested: Decimal | None) -> tuple[bool, Decimal]:
    """
    NO_SHORTS enforcement: ограничиваем объём продажи фактической позицией по базовой валюте.

    Args:
        storage: Storage порт для доступа к позициям
        symbol: Торговая пара
        requested: Запрошенный объём продажи (None = продать всё)

    Returns:
        tuple (allowed: bool, amount_to_sell: Decimal)
        Если позиции нет или недостаточно → (False, 0)
    """
    try:
        repo = getattr(storage, "positions", None)
        if repo is None:
            _log.debug("positions_repo_not_found", extra={"symbol": symbol})
            return (False, dec("0"))

        pos = repo.get_position(symbol)
        if pos is None:
            _log.debug("position_not_found", extra={"symbol": symbol})
            return (False, dec("0"))

        # Извлекаем объём базовой валюты (поддержка объектной и dict структуры)
        held_raw = getattr(pos, "base_qty", None)
        if held_raw is None and isinstance(pos, dict):
            held_raw = pos.get("base_qty")

        held = dec(str(held_raw or "0"))
        if held <= dec("0"):
            _log.debug("no_base_position", extra={"symbol": symbol, "held": str(held)})
            return (False, dec("0"))

        # Берём запрошенное значение или продаём всю позицию
        amt = dec(str(requested)) if requested is not None else held
        if amt > held:
            _log.debug(
                "requested_exceeds_position",
                extra={"symbol": symbol, "requested": str(amt), "held": str(held)},
            )
            amt = held

        return (True, amt) if amt > dec("0") else (False, dec("0"))

    except Exception as exc:
        _log.error("compute_sell_amount_failed", extra={"symbol": symbol, "error": str(exc)}, exc_info=True)
        return (False, dec("0"))


# Backward compatibility wrapper
class PositionGuard:
    """
    Совместимый враппер для старого кода — единая точка проверки NO_SHORTS.

    @deprecated: Используйте compute_sell_amount напрямую
    """

    @staticmethod
    def can_sell(storage: StoragePort, symbol: str, amount: Decimal) -> tuple[bool, Decimal]:
        """Проверяет возможность продажи указанного количества."""
        return compute_sell_amount(storage, symbol, amount)


@dataclass
class PositionsReconciler:
    """
    Сверяет локальные позиции с текущими рыночными ценами для корректного расчета PnL.

    Архитектурные принципы:
    - Работает только через порты
    - Не изменяет количество в позиции, только обновляет last_price
    - Логирует все операции с trace_id
    - Публикует события через EventBus
    """

    storage: StoragePort
    broker: BrokerPort
    bus: EventBusPort

    async def reconcile(self, *, symbol: str) -> dict[str, Any]:
        """
        Сверяет позицию для одного символа.

        Returns:
            dict с результатами операции:
            - ok: bool - успешность
            - symbol: str - торговая пара
            - position_found: bool - найдена ли позиция
            - price_updated: bool - обновлена ли цена
            - unrealized_pnl: str - нереализованная прибыль/убыток
        """
        with trace_context() as trace_id:
            _log.info("position_reconcile_started", extra={"symbol": symbol, "trace_id": trace_id})

            try:
                result = await self._reconcile_single_position(symbol, trace_id)

                if result.get("ok") and result.get("price_updated"):
                    await self._publish_position_updated(symbol, result, trace_id)

                return result

            except Exception as exc:
                _log.error(
                    "position_reconcile_failed",
                    extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
                    exc_info=True,
                )
                return {"ok": False, "symbol": symbol, "reason": "reconcile_failed", "trace_id": trace_id}

    async def reconcile_batch(self, *, symbols: list[str]) -> dict[str, Any]:
        """
        Сверяет позиции для множества символов.
        """
        with trace_context() as trace_id:
            _log.info(
                "positions_batch_reconcile_started",
                extra={"symbols": symbols, "count": len(symbols), "trace_id": trace_id},
            )

            results: list[dict[str, Any]] = []
            success_count = 0

            for symbol in symbols:
                try:
                    result = await self._reconcile_single_position(symbol, trace_id)
                    results.append(result)
                    if result.get("ok"):
                        success_count += 1
                        if result.get("price_updated"):
                            await self._publish_position_updated(symbol, result, trace_id)
                except Exception as exc:
                    _log.warning(
                        "position_reconcile_symbol_failed",
                        extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
                    )
                    results.append({"ok": False, "symbol": symbol, "reason": "exception"})

            # Публикуем событие завершения batch reconciliation
            await self._publish_reconciliation_completed(symbols, success_count, trace_id)

            return {
                "ok": True,
                "total_symbols": len(symbols),
                "success_count": success_count,
                "failed_count": len(symbols) - success_count,
                "results": results,
                "trace_id": trace_id,
            }

    async def _reconcile_single_position(self, symbol: str, trace_id: str) -> dict[str, Any]:
        """Выполняет сверку одной позиции."""
        # Получаем текущую цену с биржи
        try:
            ticker = await self.broker.fetch_ticker(symbol)
        except Exception as exc:
            _log.debug("ticker_fetch_failed", extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)})
            return {"ok": False, "symbol": symbol, "position_found": False, "price_updated": False, "reason": "ticker_error"}

        last_price = self._extract_last_price(ticker)
        if last_price <= dec("0"):
            _log.debug("no_valid_price", extra={"symbol": symbol, "trace_id": trace_id})
            return {"ok": False, "symbol": symbol, "position_found": False, "price_updated": False, "reason": "no_valid_price"}

        # Получаем локальную позицию
        position = self._get_local_position(symbol)
        if not position:
            return {"ok": True, "symbol": symbol, "position_found": False, "price_updated": False, "reason": "no_position"}

        base_qty = self._extract_base_qty(position)
        if base_qty <= dec("0"):
            return {"ok": True, "symbol": symbol, "position_found": True, "price_updated": False, "reason": "no_base_quantity"}

        avg_entry = self._extract_avg_entry_price(position)
        if avg_entry <= dec("0"):
            _log.warning("no_entry_price", extra={"symbol": symbol, "trace_id": trace_id})
            return {"ok": False, "symbol": symbol, "position_found": True, "price_updated": False, "reason": "no_entry_price"}

        # Рассчитываем нереализованную прибыль
        unrealized_pnl = (last_price - avg_entry) * base_qty

        # Обновляем last_price в позиции (без изменения количества)
        updated = self._update_position_last_price(symbol, last_price)
        if not updated:
            _log.debug("position_update_skipped", extra={"symbol": symbol, "trace_id": trace_id})

        _log.debug(
            "position_reconciled",
            extra={
                "symbol": symbol,
                "last_price": str(last_price),
                "base_qty": str(base_qty),
                "avg_entry": str(avg_entry),
                "unrealized_pnl": str(unrealized_pnl),
                "trace_id": trace_id,
            },
        )

        return {
            "ok": True,
            "symbol": symbol,
            "position_found": True,
            "price_updated": bool(updated),
            "last_price": str(last_price),
            "base_qty": str(base_qty),
            "avg_entry_price": str(avg_entry),
            "unrealized_pnl": str(unrealized_pnl),
        }

    # -------- extractors --------

    def _extract_last_price(self, ticker: Any) -> Decimal:
        """
        Извлекает последнюю цену из тикера.
        Поддерживает объектные DTO (атрибуты .last/.bid/.ask/.close/.price) и Mapping.
        """
        # 1) объектный путь (TickerDTO)
        for attr in ("last", "bid", "ask", "close", "price"):
            v = getattr(ticker, attr, None)
            if v is not None:
                try:
                    price = dec(str(v))
                    if price > dec("0"):
                        return price
                except Exception:
                    pass

        # 2) dict-путь (Mapping)
        if isinstance(ticker, Mapping):
            for key in ("last", "bid", "ask", "close", "price"):
                if key in ticker and ticker[key] is not None:
                    try:
                        price = dec(str(ticker[key]))
                        if price > dec("0"):
                            return price
                    except Exception:
                        pass

        return dec("0")

    def _get_local_position(self, symbol: str) -> Any:
        """Получает локальную позицию из storage."""
        try:
            return self.storage.positions.get_position(symbol)
        except Exception as exc:
            _log.warning("get_position_failed", extra={"symbol": symbol, "error": str(exc)})
            return None

    def _extract_base_qty(self, position: Any) -> Decimal:
        """Извлекает количество базовой валюты из позиции."""
        if hasattr(position, "base_qty"):
            return dec(str(getattr(position, "base_qty") or "0"))
        if isinstance(position, dict):
            return dec(str(position.get("base_qty", "0")))
        return dec("0")

    def _extract_avg_entry_price(self, position: Any) -> Decimal:
        """Извлекает среднюю цену входа из позиции."""
        for name in ("avg_entry_price", "entry_price", "price"):
            if hasattr(position, name):
                return dec(str(getattr(position, name) or "0"))
            if isinstance(position, dict) and name in position:
                return dec(str(position.get(name, "0")))
        return dec("0")

    def _update_position_last_price(self, symbol: str, last_price: Decimal) -> bool:
        """
        Обновляет last_price позиции без изменения количества.
        Стараемся использовать apply_trade(..., base_amount=0), иначе — специализированные методы.
        """
        repo = getattr(self.storage, "positions", None)
        if repo is None:
            return False

        # 1) Предпочтительно — apply_trade с нулевым количеством (не меняет объём)
        try:
            repo.apply_trade(
                symbol=symbol,
                side="buy",  # фиктивный side
                base_amount=dec("0"),
                price=last_price,
                fee_quote=dec("0"),
                last_price=last_price,
            )
            return True
        except Exception:
            pass

        # 2) Альтернативы: update_last_price / set_last_price
        for name in ("update_last_price", "set_last_price"):
            fn = getattr(repo, name, None)
            if callable(fn):
                try:
                    fn(symbol, last_price)  # type: ignore[misc]
                    return True
                except Exception:
                    continue
        return False

    # -------- events --------

    async def _publish_position_updated(self, symbol: str, result: dict, trace_id: str) -> None:
        """Публикует событие обновления позиции (payload, не data)."""
        try:
            await self.bus.publish(
                topic=POSITIONS_UPDATED,
                payload={
                    "symbol": symbol,
                    "last_price": result.get("last_price"),
                    "unrealized_pnl": result.get("unrealized_pnl"),
                    "trace_id": trace_id,
                },
            )
        except Exception as exc:
            _log.warning(
                "position_event_publish_failed",
                extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
            )

    async def _publish_reconciliation_completed(self, symbols: list[str], success_count: int, trace_id: str) -> None:
        """Публикует событие завершения batch reconciliation (payload, не data)."""
        try:
            await self.bus.publish(
                topic=RECONCILIATION_COMPLETED,
                payload={
                    "type": "positions",
                    "symbols": symbols,
                    "total_count": len(symbols),
                    "success_count": success_count,
                    "trace_id": trace_id,
                },
            )
        except Exception as exc:
            _log.warning(
                "reconciliation_event_publish_failed",
                extra={"symbols_count": len(symbols), "trace_id": trace_id, "error": str(exc)},
            )


# Compatibility wrapper для orchestrator
async def reconcile_positions(symbol: str, storage: StoragePort, broker: BrokerPort, bus: EventBusPort, _settings: Any) -> None:
    """
    Совместимый враппер для оркестратора: сверяем только указанный символ.

    @deprecated: Используйте PositionsReconciler напрямую
    """
    reconciler = PositionsReconciler(storage=storage, broker=broker, bus=bus)
    await reconciler.reconcile(symbol=symbol)


# Batch reconciliation function
async def reconcile_positions_batch(*, symbols: list[str], storage: StoragePort, broker: BrokerPort, bus: EventBusPort) -> None:
    """
    Пересчитывает позиции для множества символов.

    @deprecated: Используйте PositionsReconciler.reconcile_batch напрямую
    """
    reconciler = PositionsReconciler(storage=storage, broker=broker, bus=bus)
    await reconciler.reconcile_batch(symbols=symbols)
