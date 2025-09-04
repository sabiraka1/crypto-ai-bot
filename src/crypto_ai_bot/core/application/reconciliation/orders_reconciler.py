from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from crypto_ai_bot.core.application.ports import BrokerPort, StoragePort
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("reconcile.orders")


def _as_list(x: Any) -> list[dict]:
    if isinstance(x, list):
        return [d for d in x if isinstance(d, dict)]
    return []


def _keyset(items: Iterable[dict]) -> set[tuple[str | None, str | None]]:
    """Нормализуем ключ: (client_order_id, broker_order_id)."""
    out: set[tuple[str | None, str | None]] = set()
    for it in items:
        coid = str(it.get("client_order_id")) if it.get("client_order_id") is not None else None
        boid = str(it.get("broker_order_id")) if it.get("broker_order_id") is not None else None
        out.add((coid, boid))
    return out


def _status(it: dict) -> str:
    return str(it.get("status") or it.get("state") or "").lower()


def _amount_pair(it: dict) -> tuple[str, str]:
    # Нормализуем до str, чтобы не тянуть Decimal внутри сверки
    return (str(it.get("amount", "0")), str(it.get("filled", "0")))


@dataclass
class OrdersReconciler:
    """Сверяет локальные «открытые» ордера с фактическими на бирже (по символу)."""

    storage: StoragePort
    broker: BrokerPort

    async def reconcile(self, *, symbol: str) -> dict[str, Any] | None:
        try:
            local = self._fetch_local_open(symbol)
            remote = await self._fetch_remote_open(symbol)
        except Exception as exc:  # broker/storage падения
            _log.error(
                "orders_reconcile_fetch_failed", extra={"symbol": symbol, "err": str(exc)}, exc_info=True
            )
            return {"ok": False, "symbol": symbol, "reason": "fetch_failed"}

        ks_local = _keyset(local)
        ks_remote = _keyset(remote)

        missing_on_broker = list(ks_local - ks_remote)
        missing_locally = list(ks_remote - ks_local)

        qty_mismatch: list[dict[str, Any]] = []
        status_mismatch: list[dict[str, Any]] = []

        # Индексация по ключам для сравнения
        idx_loc = {(c, b): it for it in local for (c, b) in [_key(it)]}
        idx_rem = {(c, b): it for it in remote for (c, b) in [_key(it)]}

        for key in ks_local & ks_remote:
            l, r = idx_loc.get(key, {}), idx_rem.get(key, {})
            if _amount_pair(l) != _amount_pair(r):
                qty_mismatch.append({"key": key, "local": _amount_pair(l), "remote": _amount_pair(r)})
            if _status(l) != _status(r):
                status_mismatch.append({"key": key, "local": _status(l), "remote": _status(r)})

        report = {
            "ok": True,
            "symbol": symbol,
            "local_open": len(local),
            "remote_open": len(remote),
            "missing_on_broker": missing_on_broker,
            "missing_locally": missing_locally,
            "qty_mismatch": qty_mismatch,
            "status_mismatch": status_mismatch,
        }

        # Логируем только при реальных расхождениях
        if any((missing_on_broker, missing_locally, qty_mismatch, status_mismatch)):
            _log.warning("orders_discrepancy", extra=report)

        return report

    # ---------- helpers ----------
    def _fetch_local_open(self, symbol: str) -> list[dict]:
        """Пытаемся аккуратно получить локальные открытые ордера (разные реализации репозитория)."""
        repo = getattr(self.storage, "orders", None)
        if repo is None:
            return []

        # пробуем популярные сигнатуры
        for name in ("list_open", "find_open", "list_symbol", "find_by_symbol", "list"):
            fn = getattr(repo, name, None)
            if callable(fn):
                try:
                    items = fn(symbol) if fn.__code__.co_argcount >= 2 else fn()  # type: ignore[attr-defined]
                    return [self._norm_order(x) for x in _as_list(items)]
                except Exception:
                    continue

        # если API объектное (ORM), пробуем .all_open / .all и фильтруем
        items = []
        for name in ("all_open", "all"):
            fn = getattr(repo, name, None)
            if callable(fn):
                try:
                    items = fn()
                    break
                except Exception:
                    continue

        out: list[dict] = []
        for it in _as_list(items):
            if str(it.get("symbol", "")).upper() == symbol.upper() and _status(it) in ("open", "new"):
                out.append(self._norm_order(it))
        return out

    async def _fetch_remote_open(self, symbol: str) -> list[dict]:
        """Получить открытые ордера у брокера (безопасно по сигнатурам)."""
        # предпочитаем fetch_open_orders, но даём деградацию до fetch_orders+фильтр
        if hasattr(self.broker, "fetch_open_orders"):
            try:
                items = await self.broker.fetch_open_orders(symbol)
                return [self._norm_order(x) for x in _as_list(items)]
            except Exception:
                pass

        if hasattr(self.broker, "fetch_orders"):
            try:
                items = await self.broker.fetch_orders(symbol)
                out = [self._norm_order(x) for x in _as_list(items)]
                return [x for x in out if _status(x) in ("open", "new")]
            except Exception:
                pass

        return []

    @staticmethod
    def _norm_order(x: dict) -> dict:
        """Нормализуем ключевые поля, используемые в сверке."""
        return {
            "symbol": x.get("symbol"),
            "client_order_id": x.get("client_order_id") or x.get("clientOrderId"),
            "broker_order_id": x.get("broker_order_id") or x.get("id") or x.get("orderId"),
            "amount": x.get("amount") or x.get("qty") or x.get("quantity"),
            "filled": x.get("filled") or x.get("executed") or x.get("executedQty"),
            "status": x.get("status") or x.get("state"),
        }


def _key(it: dict) -> tuple[str | None, str | None]:
    return (
        str(it.get("client_order_id")) if it.get("client_order_id") is not None else None,
        str(it.get("broker_order_id")) if it.get("broker_order_id") is not None else None,
    )
