# src/crypto_ai_bot/app/tasks/reconciler.py
from __future__ import annotations
import threading
import time
from typing import Any, Dict, Optional

from crypto_ai_bot.core.brokers.symbols import to_ccxt_symbol
from crypto_ai_bot.core.market_specs import quantize_amount


class _ReconcilerRunner:
    def __init__(self, container):
        self.container = container
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._loop, name="reconciler", daemon=True)

    def start(self):
        self._thr.start()
        return self

    def cancel(self):
        self._stop.set()
        try:
            self._thr.join(timeout=2.0)
        except Exception:
            pass

    # -------- main loop --------
    def _loop(self):
        period = float(getattr(self.container.settings, "RECONCILE_PERIOD_SEC", 2.0))
        while not self._stop.is_set():
            try:
                _reconcile_orders(self.container)
            except Exception as e:
                try:
                    self.container.audit_repo.log("reconcile_error", {"stage": "orders", "err": repr(e)})
                except Exception:
                    pass
            try:
                _check_protective_exits(self.container)
            except Exception as e:
                try:
                    self.container.audit_repo.log("reconcile_error", {"stage": "exits", "err": repr(e)})
                except Exception:
                    pass
            self._stop.wait(period)


def start_reconciler(container):
    return _ReconcilerRunner(container).start()


# ----------- helpers -----------

def _reconcile_orders(container):
    broker = container.broker
    repo = container.trades_repo
    audit = container.audit_repo

    pendings = repo.find_pending_orders(limit=200)
    for p in pendings:
        oid = p["order_id"]
        raw_sym = p["symbol"]
        sym_ccxt = to_ccxt_symbol(raw_sym, getattr(broker, "exchange_name", None))
        try:
            info = broker.fetch_order(oid, sym_ccxt)
        except Exception as e:
            # сетевые ошибки не меняют состояния
            try:
                audit.log("order_fetch_error", {"order_id": oid, "symbol": raw_sym, "err": repr(e)})
            except Exception:
                pass
            continue

        status = (info.get("status") or "").lower()
        filled = float(info.get("filled") or 0.0)
        avg_px = float(info.get("average") or info.get("price") or p.get("price") or 0.0)

        fee_amt = 0.0
        fee_ccy = "USDT"
        if info.get("fee"):
            fee_amt = float(info["fee"].get("cost") or 0.0)
            fee_ccy = info["fee"].get("currency") or "USDT"

        new_state = repo.record_exchange_update(
            order_id=oid,
            exchange_status=status,
            filled=filled,
            average_price=avg_px,
            fee_amt=fee_amt,
            fee_ccy=fee_ccy
        )

        if new_state in {"filled", "canceled", "rejected"}:
            try:
                audit.log("order_state_final", {"order_id": oid, "state": new_state, "symbol": raw_sym, "filled": filled, "avg_px": avg_px})
            except Exception:
                pass


def _check_protective_exits(container):
    exits_repo = container.exits_repo
    positions_repo = container.positions_repo
    broker = container.broker
    audit = container.audit_repo

    active = exits_repo.list_active(limit=200)
    by_symbol: Dict[str, list] = {}
    for x in active:
        by_symbol.setdefault(x["symbol"], []).append(x)

    for raw_sym, lst in by_symbol.items():
        sym_ccxt = to_ccxt_symbol(raw_sym, getattr(broker, "exchange_name", None))
        try:
            t = broker.fetch_ticker(sym_ccxt)
            last = float(t.get("last") or t.get("close") or 0.0)
            if last <= 0:
                continue
        except Exception:
            continue

        for x in lst:
            trig = float(x["trigger_px"])
            fire = (x["kind"] == "sl" and last <= trig) or (x["kind"] == "tp" and last >= trig)
            if fire:
                _exit_market(container, sym_ccxt, x)
                try:
                    audit.log("protective_exit_trigger", {"symbol": raw_sym, "kind": x["kind"], "trigger_px": trig, "last": last})
                except Exception:
                    pass


def _exit_market(container, symbol_ccxt: str, exit_row):
    # В long-only — продаём весь остаток
    pos_qty = container.positions_repo.long_qty(symbol_ccxt)
    if pos_qty <= 0:
        container.exits_repo.deactivate(exit_row["id"])
        return

    qty = pos_qty
    if hasattr(container.broker, "get_market"):
        m = container.broker.get_market(symbol_ccxt)
        if m:
            qty = quantize_amount(qty, m, side="sell")
            if qty <= 0:
                container.exits_repo.deactivate(exit_row["id"])
                return

    if not getattr(container.settings, "ENABLE_TRADING", False):
        container.exits_repo.deactivate(exit_row["id"])
        return

    try:
        container.broker.create_order(symbol=symbol_ccxt, type="market", side="sell", amount=qty)
        container.exits_repo.deactivate(exit_row["id"])
    except Exception as e:
        try:
            container.audit_repo.log("exit_order_error", {"symbol": symbol_ccxt, "qty": qty, "err": repr(e)})
        except Exception:
            pass
