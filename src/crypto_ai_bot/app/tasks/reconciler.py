# src/crypto_ai_bot/app/tasks/reconciler.py
import anyio
import time

POLL_SEC = 2.0


async def start_reconciler(container):
    """
    Запускает фоновой цикл и возвращает anyio.CancelScope для остановки.
    """
    tg = anyio.create_task_group()
    await tg.__aenter__()

    async def _loop():
        while True:
            try:
                _reconcile_orders(container)
                _check_protective_exits(container)
            except Exception:
                # тут можно инкрементить метрику ошибок
                pass
            await anyio.sleep(POLL_SEC)

    tg.start_soon(_loop)
    return tg.cancel_scope


def _reconcile_orders(container):
    broker = container.broker
    repo = container.trades_repo
    pendings = repo.find_pending_orders(limit=100)
    for p in pendings:
        oid = p["order_id"]
        try:
            info = broker.fetch_order(oid, p["symbol"])
        except Exception:
            continue
        status = (info.get("status") or "").lower()
        filled = float(info.get("filled") or 0.0)
        price = float(info.get("average") or info.get("price") or p["price"])
        fee = 0.0
        fee_ccy = "USDT"
        if info.get("fee"):
            fee = float(info["fee"].get("cost") or 0.0)
            fee_ccy = info["fee"].get("currency") or "USDT"

        if status in ("closed", "filled") or (filled > 0 and status in ("done", "ok")):
            repo.fill_order(order_id=oid, executed_price=price, executed_qty=filled, fee_amt=fee, fee_ccy=fee_ccy)
        elif status in ("canceled", "cancelled"):
            repo.cancel_order(order_id=oid)
        elif status in ("rejected",):
            repo.reject_order(order_id=oid)
        else:
            # pending / partial — оставляем
            pass


def _check_protective_exits(container):
    exits_repo = container.exits_repo
    positions_repo = container.positions_repo
    broker = container.broker
    active = exits_repo.list_active(limit=200)

    # группируем по символам для экономии вызовов
    by_symbol = {}
    for x in active:
        by_symbol.setdefault(x["symbol"], []).append(x)

    for sym, lst in by_symbol.items():
        try:
            t = broker.fetch_ticker(sym)
            last = float(t.get("last") or t.get("close") or 0.0)
            if last <= 0:
                continue
        except Exception:
            continue

        # проверяем триггеры
        for x in lst:
            if x["kind"] == "sl" and last <= float(x["trigger_px"]):
                _exit_market(container, sym, x)
            elif x["kind"] == "tp" and last >= float(x["trigger_px"]):
                _exit_market(container, sym, x)


def _exit_market(container, symbol: str, exit_row):
    # В long-only — продаём весь остаток по позиции (best-effort)
    if not getattr(container.settings, "ENABLE_TRADING", False):
        # paper: просто деактивируем (paper-fill можно добавить по желанию)
        container.exits_repo.deactivate(exit_row["id"])
        return

    try:
        pos_qty = container.positions_repo.long_qty(symbol)
        if pos_qty <= 0:
            container.exits_repo.deactivate(exit_row["id"])
            return
        container.broker.create_order(symbol=symbol, type="market", side="sell", amount=pos_qty)
        # ордер попадёт в pending и позже закроется реконсилиатором
        container.exits_repo.deactivate(exit_row["id"])
    except Exception:
        # можно логировать/отправлять в DLQ
        pass
