from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
import inspect

from crypto_ai_bot.core.application.ports import BrokerPort, EventBusPort, StoragePort
from crypto_ai_bot.core.application.events_topics import BALANCES_UPDATED, RECONCILIATION_COMPLETED
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import trace_context

_log = get_logger("reconcile.balances")


def _safe_decimal_from_balance(balance: Mapping[str, Any], key: str, default: str = "0") -> Decimal:
    """
    Безопасно извлекает Decimal из словаря баланса с обработкой различных форматов.
    """
    try:
        value = balance.get(key, default)
        if value is None:
            return dec(default)
        return dec(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        _log.debug(
            "balance_value_conversion_failed",
            extra={"key": key, "value": repr(value), "error": str(exc)}
        )
        return dec(default)


@dataclass
class BalancesReconciler:
    """
    Сверяет балансы аккаунта с брокером для указанного символа.

    Архитектурные принципы:
    - Работает только через BrokerPort
    - Нормализует балансы в единый формат
    - Публикует события через EventBus
    - Интегрируется с trace_id для корреляции
    - Поддерживает как SPOT, так и обобщенные балансы
    """

    broker: BrokerPort
    bus: Optional[EventBusPort] = None
    storage: Optional[StoragePort] = None

    async def reconcile(self, *, symbol: str) -> dict[str, Any]:
        """
        Выполняет сверку балансов для указанного символа.
        """
        with trace_context() as trace_id:
            _log.info("balance_reconcile_started", extra={"symbol": symbol, "trace_id": trace_id})

            try:
                # Получаем сырые балансы от брокера (глобальные), затем извлекаем нужные валюты символа
                raw_balances = await self._fetch_raw_balances(symbol)

                # Нормализуем балансы
                normalized = self._normalize_balances(symbol, raw_balances, trace_id)

                # Валидируем балансы
                validation_result = self._validate_balances(normalized, trace_id)
                if not validation_result["valid"]:
                    _log.warning(
                        "balance_validation_failed",
                        extra={"symbol": symbol, "issues": validation_result["issues"], "trace_id": trace_id},
                    )

                # Публикуем событие обновления балансов
                if self.bus:
                    await self._publish_balances_updated(symbol, normalized, trace_id)

                result = {
                    "ok": True,
                    "symbol": symbol,
                    "balances": normalized,
                    "validation": validation_result,
                    "trace_id": trace_id,
                }

                _log.info(
                    "balance_reconcile_completed",
                    extra={
                        "symbol": symbol,
                        "base_currency": normalized.get("base_currency"),
                        "quote_currency": normalized.get("quote_currency"),
                        "free_base": normalized.get("free_base"),
                        "free_quote": normalized.get("free_quote"),
                        "trace_id": trace_id,
                    },
                )
                return result

            except Exception as exc:
                _log.error(
                    "balance_reconcile_failed",
                    extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
                    exc_info=True,
                )
                return {
                    "ok": False,
                    "symbol": symbol,
                    "reason": "reconcile_failed",
                    "error": str(exc),
                    "trace_id": trace_id,
                }

    async def reconcile_batch(self, *, symbols: list[str]) -> dict[str, Any]:
        """Сверяет балансы для множества символов."""
        with trace_context() as trace_id:
            _log.info(
                "balances_batch_reconcile_started",
                extra={"symbols": symbols, "count": len(symbols), "trace_id": trace_id},
            )

            results = []
            success_count = 0

            for symbol in symbols:
                try:
                    result = await self.reconcile(symbol=symbol)
                    results.append(result)
                    if result["ok"]:
                        success_count += 1
                except Exception as exc:
                    _log.warning(
                        "balance_reconcile_symbol_failed",
                        extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
                    )
                    results.append({"ok": False, "symbol": symbol, "reason": "exception", "error": str(exc)})

            # Публикуем событие завершения batch reconciliation
            if self.bus:
                await self._publish_reconciliation_completed(symbols, success_count, trace_id)

            return {
                "ok": True,
                "total_symbols": len(symbols),
                "success_count": success_count,
                "failed_count": len(symbols) - success_count,
                "results": results,
                "trace_id": trace_id,
            }

    async def _fetch_raw_balances(self, symbol: str) -> dict[str, Any]:
        """
        Получает сырые балансы от брокера и приводит их к виду для одной пары:
        { free_base, free_quote, used_base, used_quote, total_base, total_quote }
        """
        try:
            # Предпочитаем broker.fetch_balance() без аргументов (как в PaperBroker)
            fb = getattr(self.broker, "fetch_balance", None)
            if callable(fb):
                try:
                    sig = inspect.signature(fb)
                    # Если метод принимает аргументы, пробуем символ-специфичный вызов
                    params = [p for p in sig.parameters.values()
                              if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
                    if len(params) >= 1:
                        maybe_symbol_balances = await fb(symbol)  # type: ignore[misc]
                        # Если уже пришло в нужной форме — возвращаем как есть
                        if isinstance(maybe_symbol_balances, Mapping) and (
                            "free_base" in maybe_symbol_balances or "free_quote" in maybe_symbol_balances
                        ):
                            return dict(maybe_symbol_balances)
                        # Иначе извлекаем нужные валюты
                        return self._extract_symbol_balances(symbol, maybe_symbol_balances)
                except (TypeError, ValueError):
                    # если не удалось прочитать сигнатуру — ниже попробуем без аргументов
                    pass

                # Обычный путь: глобальные балансы → вырезаем нужные валюты
                all_balances = await fb()
                return self._extract_symbol_balances(symbol, all_balances)

            # Fallback к общему методу
            fab = getattr(self.broker, "fetch_account_balance", None)
            if callable(fab):
                all_balances = await fab()
                return self._extract_symbol_balances(symbol, all_balances)

            raise AttributeError("Broker does not support balance fetching")

        except Exception as exc:
            _log.error("fetch_balances_failed", extra={"symbol": symbol, "error": str(exc)}, exc_info=True)
            raise

    def _extract_symbol_balances(self, symbol: str, all_balances: Mapping[str, Any] | Any) -> dict[str, Any]:
        """Извлекает балансы базовой и котируемой валют для конкретного символа из общих балансов."""
        base_currency, quote_currency = symbol.split("/")

        def _free_of(x: Any) -> str:
            # BalanceDTO.free
            if hasattr(x, "free"):
                try:
                    return str(getattr(x, "free"))
                except Exception:
                    pass
            # dict-like {free: ...}
            if isinstance(x, Mapping):
                v = x.get("free")
                if v is not None:
                    return str(v)
            # примитив — трактуем как free
            return str(x)

        result = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "free_base": "0",
            "free_quote": "0",
        }

        try:
            if isinstance(all_balances, Mapping):
                if base_currency in all_balances:
                    result["free_base"] = _free_of(all_balances[base_currency])
                if quote_currency in all_balances:
                    result["free_quote"] = _free_of(all_balances[quote_currency])
            else:
                # неизвестный формат — оставим нули и залогируем
                _log.debug("unknown_balances_format", extra={"type": type(all_balances).__name__})
        except Exception as exc:
            _log.debug("extract_symbol_balances_failed", extra={"symbol": symbol, "error": str(exc)})

        return result

    def _normalize_balances(self, symbol: str, raw_balances: dict, trace_id: str) -> dict[str, Any]:
        """
        Нормализует сырые балансы в единый формат.
        """
        base_currency, quote_currency = symbol.split("/")

        free_base = _safe_decimal_from_balance(raw_balances, "free_base", "0")
        free_quote = _safe_decimal_from_balance(raw_balances, "free_quote", "0")

        used_base = _safe_decimal_from_balance(raw_balances, "used_base", "0")
        used_quote = _safe_decimal_from_balance(raw_balances, "used_quote", "0")
        total_base = _safe_decimal_from_balance(raw_balances, "total_base", str(free_base + used_base))
        total_quote = _safe_decimal_from_balance(raw_balances, "total_quote", str(free_quote + used_quote))

        normalized = {
            "symbol": symbol,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "free_base": str(free_base),
            "free_quote": str(free_quote),
            "used_base": str(used_base),
            "used_quote": str(used_quote),
            "total_base": str(total_base),
            "total_quote": str(total_quote),
            "timestamp": raw_balances.get("timestamp") or "now",
        }

        _log.debug("balances_normalized", extra={"symbol": symbol, "normalized": normalized, "trace_id": trace_id})
        return normalized

    def _validate_balances(self, balances: dict, trace_id: str) -> dict[str, Any]:
        """
        Валидирует нормализованные балансы на корректность.
        """
        issues: list[str] = []

        try:
            free_base = dec(balances["free_base"])
            free_quote = dec(balances["free_quote"])
            used_base = dec(balances["used_base"])
            used_quote = dec(balances["used_quote"])
            total_base = dec(balances["total_base"])
            total_quote = dec(balances["total_quote"])

            # Проверка отрицательных значений
            if free_base < dec("0"):
                issues.append(f"negative_free_base: {free_base}")
            if free_quote < dec("0"):
                issues.append(f"negative_free_quote: {free_quote}")
            if used_base < dec("0"):
                issues.append(f"negative_used_base: {used_base}")
            if used_quote < dec("0"):
                issues.append(f"negative_used_quote: {used_quote}")

            # Проверка соответствия total = free + used
            if abs(total_base - (free_base + used_base)) > dec("0.00000001"):
                issues.append(f"base_total_mismatch: {total_base} != {free_base} + {used_base}")
            if abs(total_quote - (free_quote + used_quote)) > dec("0.00000001"):
                issues.append(f"quote_total_mismatch: {total_quote} != {free_quote} + {used_quote}")

        except (ValueError, KeyError) as exc:
            issues.append(f"validation_error: {exc}")

        valid = len(issues) == 0

        if not valid:
            _log.debug("balance_validation_issues", extra={"issues": issues, "balances": balances, "trace_id": trace_id})

        return {"valid": valid, "issues": issues}

    async def _publish_balances_updated(self, symbol: str, balances: dict, trace_id: str) -> None:
        """Публикует событие обновления балансов (payload, не data)."""
        try:
            await self.bus.publish(
                topic=BALANCES_UPDATED,
                payload={
                    "symbol": symbol,
                    "base_currency": balances["base_currency"],
                    "quote_currency": balances["quote_currency"],
                    "free_base": balances["free_base"],
                    "free_quote": balances["free_quote"],
                    "total_base": balances["total_base"],
                    "total_quote": balances["total_quote"],
                    "trace_id": trace_id,
                },
            )
        except Exception as exc:
            _log.warning(
                "balance_event_publish_failed",
                extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
            )

    async def _publish_reconciliation_completed(self, symbols: list[str], success_count: int, trace_id: str) -> None:
        """Публикует событие завершения batch reconciliation (payload, не data)."""
        try:
            await self.bus.publish(
                topic=RECONCILIATION_COMPLETED,
                payload={
                    "type": "balances",
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


# Backward compatibility wrapper для orchestrator
async def reconcile_balances(
    symbol: str,
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
    _settings: Any,
) -> None:
    """
    Совместимый враппер для оркестратора: сверяем балансы для указанного символа.

    @deprecated: Используйте BalancesReconciler напрямую
    """
    reconciler = BalancesReconciler(broker=broker, bus=bus, storage=storage)
    await reconciler.reconcile(symbol=symbol)


# Batch reconciliation function
async def reconcile_balances_batch(
    *,
    symbols: list[str],
    storage: StoragePort,
    broker: BrokerPort,
    bus: EventBusPort,
) -> None:
    """
    Сверяет балансы для множества символов.

    @deprecated: Используйте BalancesReconciler.reconcile_batch напрямую
    """
    reconciler = BalancesReconciler(broker=broker, bus=bus, storage=storage)
    await reconciler.reconcile_batch(symbols=symbols)
