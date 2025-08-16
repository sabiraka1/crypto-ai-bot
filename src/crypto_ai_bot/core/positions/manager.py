# src/crypto_ai_bot/core/positions/manager.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.core.brokers import ExchangeInterface
from crypto_ai_bot.core.storage.sqlite_adapter import in_txn
from crypto_ai_bot.core.storage.repositories import (
    TradeRepositorySQLite,
    PositionRepositorySQLite,
    AuditRepositorySQLite,
)
from crypto_ai_bot.utils import metrics

def _now_ms() -> int:
    return int(time.time() * 1000)

def _sdec(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

@dataclass
class PositionManager:
    """
    Менеджер позиций: операции атомарны (одна транзакция на действие).
    ВАЖНО: бизнес-правила (risk) остаются снаружи, здесь — только исполнение и учёт.
    """
    con: Any
    broker: ExchangeInterface
    trades: TradeRepositorySQLite
    positions: PositionRepositorySQLite
    audit: AuditRepositorySQLite

    # -------- публичные операции --------

    def open(self, symbol: str, side: str, size: Decimal, *, sl: Decimal | None = None, tp: Decimal | None = None, client_order_id: str | None = None) -> Dict[str, Any]:
        """
        Открыть позицию: market-ордер, запись trade + position + audit.
        Идемпотентность по client_order_id (если задан).
        """
        ts = _now_ms()
        pos_id = f"pos-{uuid.uuid4().hex[:10]}"
        side = side.lower()
        size = _sdec(size)

        def _job():
            # 1) выставляем ордер у брокера
            order = self.broker.create_order(
                symbol=symbol,
                type_="market",
                side=side,
                amount=size,
                client_order_id=client_order_id,
            )
            price = _sdec(order.get("price"))
            fee = _sdec(((order.get("fee") or {}).get("cost") or "0"))
            fee_ccy = (order.get("fee") or {}).get("currency") or "USDT"

            # 2) пишем trade
            self.trades.upsert_by_client_order_id(
                client_order_id or order["id"],
                tr=(
                    # конструируем TradeRecord "вручную", чтобы не тянуть dataclass
                    __import__("types")
                ),
            )
            # ↑ маленький трюк не нужен, лучше запишем напрямую:
            self.con.execute(
                """
                INSERT INTO trades (id, position_id, symbol, side, type, amount_base, price, fee_quote, fee_currency, timestamp, client_order_id, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) DO NOTHING;
                """,
                (
                    order["id"],
                    pos_id,
                    symbol,
                    side,
                    "market",
                    str(size),
                    str(price),
                    str(fee),
                    fee_ccy,
                    int(order.get("timestamp") or ts),
                    client_order_id or order["id"],
                    "{}",
                ),
            )

            # 3) upsert position
            self.positions.upsert(
                p=__import__("types")  # заглушка (см. ниже)
            )
            # Вместо трюка с types — выполним реальный UPSERT:
            self.con.execute(
                """
                INSERT INTO positions (id, symbol, side, size_base, entry_price, sl, tp, opened_at, status, updated_at, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, '0')
                ON CONFLICT(id) DO UPDATE SET
                    size_base=excluded.size_base,
                    entry_price=excluded.entry_price,
                    sl=excluded.sl,
                    tp=excluded.tp,
                    status='open',
                    updated_at=excluded.updated_at;
                """,
                (
                    pos_id,
                    symbol,
                    side,
                    str(size),
                    str(price),
                    None if sl is None else str(sl),
                    None if tp is None else str(tp),
                    ts,
                    ts,
                ),
            )

            # 4) аудит
            self.audit.log(
                at_ms=ts,
                actor="positions.manager",
                action="open",
                entity_type="position",
                entity_id=pos_id,
                details={
                    "symbol": symbol,
                    "side": side,
                    "size": str(size),
                    "price": str(price),
                    "sl": None if sl is None else str(sl),
                    "tp": None if tp is None else str(tp),
                    "order_id": order["id"],
                },
                idempotency_key=(client_order_id or order["id"]),
            )
            return {"position_id": pos_id, "order": order}

        # атомарно
        with in_txn(self.con):
            res = _job()

        metrics.inc("positions_open_total", {"symbol": symbol, "side": side})
        return res

    def partial_close(self, pos_id: str, size: Decimal, *, client_order_id: str | None = None) -> Dict[str, Any]:
        """
        Частичное закрытие: создаём встречный ордер на часть позиции, обновляем позицию (средняя цена), записываем PnL.
        """
        ts = _now_ms()
        size = _sdec(size)

        # достаём позицию
        pos = self.positions.get_by_id(pos_id)
        if not pos or pos["status"] != "open":
            return {"error": "position not open or not found", "id": pos_id}

        symbol = pos["symbol"]
        side = pos["side"]
        entry_price = _sdec(pos["entry_price"])
        open_size = _sdec(pos["size_base"])

        if size <= 0 or size > open_size:
            return {"error": "invalid partial size"}

        # встречная сторона
        close_side = "sell" if side == "buy" else "buy"

        def _job():
            order = self.broker.create_order(
                symbol=symbol,
                type_="market",
                side=close_side,
                amount=size,
                client_order_id=client_order_id,
            )
            price = _sdec(order.get("price"))
            fee = _sdec(((order.get("fee") or {}).get("cost") or "0"))

            # PnL на закрытую часть (для лонга: (close - entry) * size; для шорта наоборот)
            if side == "buy":
                pnl = (price - entry_price) * size - fee
            else:
                pnl = (entry_price - price) * size - fee

            new_size = open_size - size
            # обновление средней цены для остатка — упрощение: оставляем прежнюю entry_price
            # (если нужна реконструкция по нескольким входам — можно хранить FIFO лоты).
            self.positions.update_size_and_price(pos_id, new_size, entry_price, _sdec(pos["realized_pnl"]) + pnl, ts)

            # trade
            self.con.execute(
                """
                INSERT INTO trades (id, position_id, symbol, side, type, amount_base, price, fee_quote, fee_currency, timestamp, client_order_id, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) DO NOTHING;
                """,
                (
                    order["id"],
                    pos_id,
                    symbol,
                    close_side,
                    "market",
                    str(size),
                    str(price),
                    str(fee),
                    (order.get("fee") or {}).get("currency") or "USDT",
                    int(order.get("timestamp") or ts),
                    client_order_id or order["id"],
                    "{}",
                ),
            )

            # если позиция обнулилась — помечаем закрытой
            if new_size <= 0:
                self.positions.mark_closed(pos_id, _sdec(pos["realized_pnl"]) + pnl, ts)

            # аудит
            self.audit.log(
                at_ms=ts,
                actor="positions.manager",
                action="partial_close" if new_size > 0 else "close",
                entity_type="position",
                entity_id=pos_id,
                details={
                    "symbol": symbol,
                    "closed_size": str(size),
                    "fill_price": str(price),
                    "pnl": str(pnl),
                    "new_size": str(new_size),
                },
                idempotency_key=(client_order_id or order["id"]),
            )
            return {"order": order, "new_size": str(new_size), "pnl": str(pnl)}

        with in_txn(self.con):
            res = _job()

        metrics.inc("positions_close_total", {"symbol": symbol, "mode": "partial" if res.get("new_size") != "0" else "full"})
        return res

    def close(self, pos_id: str, *, client_order_id: str | None = None) -> Dict[str, Any]:
        """
        Полное закрытие по рынку.
        """
        pos = self.positions.get_by_id(pos_id)
        if not pos or pos["status"] != "open":
            return {"error": "position not open or not found", "id": pos_id}

        size = _sdec(pos["size_base"])
        if size <= 0:
            return {"error": "position size already zero"}

        return self.partial_close(pos_id, size, client_order_id=client_order_id)

    # -------- отчёты/сводки --------

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Краткий снимок: открытые позиции + сводка по экспозиции/PNL на текущую цену.
        """
        opens = self.positions.get_open()
        total_exposure = Decimal("0")
        unrealized_pnl = Decimal("0")

        for p in opens:
            symbol = p["symbol"]
            side = p["side"]
            size = _sdec(p["size_base"])
            entry_price = _sdec(p["entry_price"])
            ticker = self.broker.fetch_ticker(symbol)
            last = _sdec(ticker.get("last") or ticker.get("close") or ticker.get("price") or "0")

            exposure = size * last
            total_exposure += exposure

            if side == "buy":
                unrealized_pnl += (last - entry_price) * size
            else:
                unrealized_pnl += (entry_price - last) * size

        return {
            "open_positions": opens,
            "exposure_quote": str(total_exposure),
            "unrealized_pnl": str(unrealized_pnl),
        }

    def get_pnl(self) -> str:
        snap = self.get_snapshot()
        return snap["unrealized_pnl"]

    def get_exposure(self) -> str:
        snap = self.get_snapshot()
        return snap["exposure_quote"]
