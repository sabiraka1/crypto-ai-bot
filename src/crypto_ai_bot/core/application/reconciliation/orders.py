from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import is_dataclass, asdict
import inspect
from typing import Any

from crypto_ai_bot.core.application.ports import BrokerPort, StoragePort
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import trace_context

_log = get_logger("reconcile.orders")


# ----------------------------- helpers -----------------------------

def _iter_items(x: Any) -> list[Any]:
    """
    Приводит к списку, осторожно:
    - None → []
    - dict → [dict]
    - Iterable[Any] → list(...)
    - одиночные объекты → [obj] (если это не строка/байты)
    """
    if x is None:
        return []
    if isinstance(x, Mapping):
        return [x]
    if isinstance(x, (str, bytes)):
        return []
    if isinstance(x, Iterable):
        return list(x)
    return [x]


def _field(obj: Any, *names: str) -> Any:
    """
    Достаёт поле из dict/объекта по списку возможных имён.
    Возвращает первый найденный вариант или None.
    """
    if isinstance(obj, Mapping):
        for n in names:
            if n in obj:
                return obj.get(n)
    for n in names:
        if hasattr(obj, n):
            try:
                return getattr(obj, n)
            except Exception:
                pass
    return None


def _to_mapping(obj: Any) -> dict[str, Any]:
    """
    Унифицирует объект ордера в dict:
    - dict → копия
    - dataclass → asdict
    - объект → извлекаем интересующие поля через _field(...)
    """
    if isinstance(obj, Mapping):
        return dict(obj)

    if is_dataclass(obj):
        try:
            return asdict(obj)
        except Exception:
            pass

    # минимально достаточное представление для сравнения
    return {
        "symbol": _field(obj, "symbol"),
        "client_order_id": _field(obj, "client_order_id", "clientOrderId", "client_oid", "clientOid"),
        "broker_order_id": _field(obj, "broker_order_id", "id", "orderId"),
        "amount": _field(obj, "amount", "qty", "quantity"),
        "filled": _field(obj, "filled", "executed", "executedQty"),
        "status": _field(obj, "status", "state"),
    }


def _as_list_of_dicts(x: Any) -> list[dict[str, Any]]:
    """Нормализует вход в список словарей, отбрасывая всё неконвертируемое."""
    out: list[dict[str, Any]] = []
    for it in _iter_items(x):
        try:
            m = _to_mapping(it)
            if isinstance(m, Mapping):
                out.append(dict(m))
        except Exception:
            # молча пропускаем мусор, логируем в debug
            _log.debug("order_normalize_failed", extra={"type": type(it).__name__})
    return out


def _keyset(items: Iterable[dict]) -> set[tuple[str | None, str | None]]:
    """Нормализуем ключ: (client_order_id, broker_order_id)."""
    out: set[tuple[str | None, str | None]] = set()
    for it in items:
        coid = _coerce_str(it.get("client_order_id"))
        boid = _coerce_str(it.get("broker_order_id"))
        out.add((coid, boid))
    return out


def _status(it: dict) -> str:
    """Нормализует статус ордера."""
    v = it.get("status") or it.get("state") or ""
    try:
        return str(v).lower()
    except Exception:
        return ""


def _amount_pair(it: dict) -> tuple[str, str]:
    """Возвращает пару (amount, filled) как строки для сравнения."""
    return (str(it.get("amount", "0")), str(it.get("filled", "0")))


def _key(it: dict) -> tuple[str | None, str | None]:
    """Извлекает ключ ордера для сравнения."""
    return (_coerce_str(it.get("client_order_id")), _coerce_str(it.get("broker_order_id")))


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


# ----------------------------- core -----------------------------

class OrdersReconciler:
    """
    Сверяет локальные «открытые» ордера с фактическими на бирже по символу.

    Архитектурные принципы:
    - Работает только через порты (BrokerPort, StoragePort)
    - Логирует все расхождения с trace_id
    - Безопасная деградация при недоступности источников
    """

    def __init__(self, storage: StoragePort, broker: BrokerPort) -> None:
        self.storage = storage
        self.broker = broker

    async def reconcile(self, *, symbol: str) -> dict[str, Any]:
        """
        Выполняет сверку ордеров для указанного символа.

        Returns:
            dict с результатами сверки:
            - ok: bool - успешность операции
            - symbol: str - торговая пара
            - local_open: int - количество локальных открытых ордеров
            - remote_open: int - количество ордеров на бирже
            - missing_on_broker: list - ордера есть локально, нет на бирже
            - missing_locally: list - ордера есть на бирже, нет локально
            - qty_mismatch: list - расхождения в количестве/исполнении
            - status_mismatch: list - расхождения в статусе
        """
        with trace_context() as trace_id:
            _log.info(
                "orders_reconcile_started",
                extra={"symbol": symbol, "trace_id": trace_id},
            )

            try:
                local = self._fetch_local_open(symbol)
                remote = await self._fetch_remote_open(symbol)
            except Exception as exc:
                _log.error(
                    "orders_reconcile_fetch_failed",
                    extra={"symbol": symbol, "trace_id": trace_id, "error": str(exc)},
                    exc_info=True,
                )
                return {
                    "ok": False,
                    "symbol": symbol,
                    "reason": "fetch_failed",
                    "trace_id": trace_id,
                }

            report = self._analyze_discrepancies(symbol, local, remote, trace_id)

            # Логируем только при реальных расхождениях
            if self._has_discrepancies(report):
                _log.warning("orders_discrepancy_detected", extra={**report, "trace_id": trace_id})
            else:
                _log.debug(
                    "orders_reconcile_clean",
                    extra={
                        "symbol": symbol,
                        "local_count": len(local),
                        "remote_count": len(remote),
                        "trace_id": trace_id,
                    },
                )

            return report

    def _analyze_discrepancies(
        self,
        symbol: str,
        local: list[dict],
        remote: list[dict],
        trace_id: str,
    ) -> dict[str, Any]:
        """Анализирует расхождения между локальными и удаленными ордерами."""
        ks_local = _keyset(local)
        ks_remote = _keyset(remote)

        missing_on_broker = list(ks_local - ks_remote)
        missing_locally = list(ks_remote - ks_local)

        qty_mismatch: list[dict[str, Any]] = []
        status_mismatch: list[dict[str, Any]] = []

        # Индексация по ключам для сравнения
        idx_loc = {_key(it): it for it in local}
        idx_rem = {_key(it): it for it in remote}

        for key in ks_local & ks_remote:
            l, r = idx_loc.get(key, {}), idx_rem.get(key, {})

            if _amount_pair(l) != _amount_pair(r):
                qty_mismatch.append({"key": key, "local": _amount_pair(l), "remote": _amount_pair(r)})

            if _status(l) != _status(r):
                status_mismatch.append({"key": key, "local": _status(l), "remote": _status(r)})

        return {
            "ok": True,
            "symbol": symbol,
            "local_open": len(local),
            "remote_open": len(remote),
            "missing_on_broker": missing_on_broker,
            "missing_locally": missing_locally,
            "qty_mismatch": qty_mismatch,
            "status_mismatch": status_mismatch,
            "trace_id": trace_id,
        }

    def _has_discrepancies(self, report: dict[str, Any]) -> bool:
        """Проверяет наличие расхождений в отчете."""
        return any(
            [
                report.get("missing_on_broker"),
                report.get("missing_locally"),
                report.get("qty_mismatch"),
                report.get("status_mismatch"),
            ]
        )

    def _fetch_local_open(self, symbol: str) -> list[dict]:
        """
        Получает локальные открытые ордера из storage.

        Безопасно пытается различные API-сигнатуры репозитория и форматы элементов.
        """
        repo = getattr(self.storage, "orders", None)
        if repo is None:
            _log.debug("orders_repo_not_found", extra={"symbol": symbol})
            return []

        # Популярные сигнатуры методов репозитория
        candidates = ("list_open", "find_open", "list_symbol", "find_by_symbol", "list", "all_open", "all")

        for method_name in candidates:
            method = getattr(repo, method_name, None)
            if not callable(method):
                continue
            try:
                # Аккуратно определяем, надо ли передавать symbol:
                sig = None
                try:
                    sig = inspect.signature(method)
                except (TypeError, ValueError):
                    pass

                if sig:
                    # количество параметров, исключая *args/**kwargs
                    params = [
                        p
                        for p in sig.parameters.values()
                        if p.kind
                        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                    ]
                    # для bound-метода self уже привязан → 0 означает без параметров
                    needs_symbol = len(params) >= 1
                else:
                    # Если не смогли определить — пробуем обе формы
                    needs_symbol = True

                items = method(symbol) if needs_symbol else method()
                normalized = [_normalize_order(x) for x in _iter_items(items)]
                # Если метод «общий» (all/all_open), подфильтруем по символу/статусу
                if method_name in ("all", "all_open"):
                    normalized = [
                        it
                        for it in normalized
                        if str(it.get("symbol", "")).upper() == symbol.upper()
                        and _status(it) in ("open", "new")
                    ]
                return normalized
            except TypeError:
                # Вторая попытка — без аргумента (или наоборот — с аргументом)
                try:
                    items = method()
                    normalized = [_normalize_order(x) for x in _iter_items(items)]
                    if method_name in ("all", "all_open"):
                        normalized = [
                            it
                            for it in normalized
                            if str(it.get("symbol", "")).upper() == symbol.upper()
                            and _status(it) in ("open", "new")
                        ]
                    return normalized
                except Exception as exc2:
                    _log.debug(
                        "orders_method_failed_fallback",
                        extra={"symbol": symbol, "method": method_name, "error": str(exc2)},
                    )
                    continue
            except Exception as exc:
                _log.debug(
                    "orders_method_failed",
                    extra={"symbol": symbol, "method": method_name, "error": str(exc)},
                )
                continue

        _log.warning("orders_no_working_method", extra={"symbol": symbol})
        return []

    async def _fetch_remote_open(self, symbol: str) -> list[dict]:
        """
        Получает открытые ордера у брокера с безопасной деградацией.
        Поддерживает возвращаемые списки DTO/датаклассов и dict.
        """
        # Предпочитаем fetch_open_orders(symbol)
        if hasattr(self.broker, "fetch_open_orders"):
            try:
                items = await self.broker.fetch_open_orders(symbol)
                return [_normalize_order(x) for x in _iter_items(items)]
            except Exception as exc:
                _log.debug("fetch_open_orders_failed", extra={"symbol": symbol, "error": str(exc)})

        # Деградация до fetch_orders + фильтр
        if hasattr(self.broker, "fetch_orders"):
            try:
                items = await self.broker.fetch_orders(symbol)
                normalized = [_normalize_order(x) for x in _iter_items(items)]
                return [x for x in normalized if _status(x) in ("open", "new")]
            except Exception as exc:
                _log.debug("fetch_orders_failed", extra={"symbol": symbol, "error": str(exc)})

        _log.warning("remote_orders_unavailable", extra={"symbol": symbol})
        return []


def _normalize_order(order: Any) -> dict[str, Any]:
    """
    Нормализует ключевые поля ордера для унифицированной работы.
    Поддерживает dict/датаклассы/объекты.
    """
    if isinstance(order, Mapping) or is_dataclass(order):
        d = _to_mapping(order)
    else:
        d = _to_mapping(order)

    # минимальная нормализация ключей
    return {
        "symbol": d.get("symbol"),
        "client_order_id": d.get("client_order_id") or d.get("clientOrderId") or d.get("client_oid") or d.get("clientOid"),
        "broker_order_id": d.get("broker_order_id") or d.get("id") or d.get("orderId"),
        "amount": d.get("amount") or d.get("qty") or d.get("quantity"),
        "filled": d.get("filled") or d.get("executed") or d.get("executedQty"),
        "status": d.get("status") or d.get("state"),
    }
