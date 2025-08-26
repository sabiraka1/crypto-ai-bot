#!/usr/bin/env python3
"""
Manual reconciliation tool — детализированные сверки и sanity-check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from typing import Any, Dict, List

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.reconciliation.positions import PositionsReconciler
from crypto_ai_bot.core.reconciliation.balances import BalancesReconciler
from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger

log = get_logger("reconciler")


class ManualReconciler:
    def __init__(self, container):
        self.container = container
        self.symbol = container.settings.SYMBOL

    async def run_full(self, auto_fix: bool) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "symbol": self.symbol,
            "timestamp": now_ms(),
            "orders": {},
            "positions": {},
            "balances": {},
            "discrepancies": [],
            "actions_taken": [],
            "status": "OK",
        }

        # 1) Orders
        try:
            orders_rec = OrdersReconciler(self.container.broker, self.symbol)
            rep = await orders_rec.run_once()
            report["orders"] = rep
            if rep.get("supported") and rep.get("open_orders", 0) > 0:
                report["discrepancies"].append(
                    {"type": "hanging_orders", "count": rep["open_orders"], "ids": rep.get("ids", [])[:10]}
                )
        except Exception as e:
            log.error("orders_reconciliation_failed", extra={"error": str(e)})
            report["orders"] = {"error": str(e)}

        # 2) Positions
        try:
            pos_rec = PositionsReconciler(storage=self.container.storage, broker=self.container.broker, symbol=self.symbol)
            rep = await pos_rec.run_once()
            report["positions"] = rep
            if "error" not in rep:
                local = Decimal(str(rep.get("local_base", "0")))
                exchange = Decimal(str(rep.get("exchange_base", "0")))
                diff = abs(local - exchange)
                if diff > Decimal("0.00000001"):
                    report["discrepancies"].append(
                        {"type": "position_mismatch", "local": str(local), "exchange": str(exchange), "diff": str(diff)}
                    )
                    if auto_fix:
                        setter = getattr(self.container.storage.positions, "set_base_qty", None)
                        if callable(setter):
                            setter(self.symbol, exchange)
                            report["actions_taken"].append(
                                {"action": "position_corrected", "old": str(local), "new": str(exchange)}
                            )
        except Exception as e:
            log.error("positions_reconciliation_failed", extra={"error": str(e)})
            report["positions"] = {"error": str(e)}

        # 3) Balances
        try:
            bal_rec = BalancesReconciler(self.container.broker, self.symbol)
            report["balances"] = await bal_rec.run_once()
        except Exception as e:
            log.error("balances_reconciliation_failed", extra={"error": str(e)})
            report["balances"] = {"error": str(e)}

        # Итог
        if report["discrepancies"]:
            report["status"] = "DISCREPANCIES_FOUND"
            report["requires_action"] = True
        else:
            report["requires_action"] = False
        return report

    async def check_only(self) -> Dict[str, Any]:
        """Санити-проверки БД без общения с биржей."""
        checks: Dict[str, Any] = {}

        # 1. Сумма trades = позиция (если есть таблица trades)
        try:
            cur = self.container.storage.conn.execute(
                "SELECT side, SUM(amount) as total FROM trades WHERE symbol = ? GROUP BY side",
                (self.symbol,),
            )
            rows = cur.fetchall()
            buys = sum(float(r[1]) for r in rows if r[0] == "buy")
            sells = sum(float(r[1]) for r in rows if r[0] == "sell")
            calculated = buys - sells
            stored = float(self.container.storage.positions.get_base_qty(self.symbol) or 0)
            checks["position_consistency"] = {
                "calculated": calculated,
                "stored": stored,
                "match": abs(calculated - stored) < 1e-8,
            }
        except Exception:
            # таблицы может не быть — не считаем это фатальной ошибкой
            checks["position_consistency"] = {"skipped": True}

        # 2. Просроченные idempotency_keys
        try:
            expired = self.container.storage.conn.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE expires_at_ms < ?",
                (now_ms(),),
            ).fetchone()[0]
            checks["expired_idempotency_keys"] = int(expired)
        except Exception:
            checks["expired_idempotency_keys"] = "unknown"

        # 3. Дубли client_order_id
        try:
            cur = self.container.storage.conn.execute(
                "SELECT client_order_id, COUNT(*) as cnt FROM trades GROUP BY client_order_id HAVING cnt > 1"
            )
            dups = [{"client_order_id": r[0], "count": r[1]} for r in cur.fetchall()]
            checks["duplicate_orders"] = dups
        except Exception:
            checks["duplicate_orders"] = "unknown"

        return checks


async def _async_main() -> int:
    parser = argparse.ArgumentParser(description="Manual reconciliation tool")
    parser.add_argument("--symbol", help="Override symbol from env")
    parser.add_argument("--auto-fix", action="store_true", help="Auto-correct local position if mismatch")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--check-only", action="store_true", help="Run consistency checks only (no broker calls)")
    args = parser.parse_args()

    c = build_container()
    if args.symbol:
        # не меняем storage, просто используем символ при вызовах
        c.settings.SYMBOL = args.symbol

    mr = ManualReconciler(c)
    if args.check_only:
        result = await mr.check_only()
    else:
        result = await mr.run_full(auto_fix=args.auto_fix)

    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        # лаконичный текстовый отчёт
        print("\n" + "=" * 60)
        print(f"RECONCILIATION REPORT — {result.get('symbol','UNKNOWN')}")
        print("=" * 60)
        if "orders" in result:
            o = result["orders"]
            if isinstance(o, dict) and "error" in o:
                print(f"📦 ORDERS: ❌ {o['error']}")
            else:
                print(f"📦 ORDERS: open={o.get('open_orders',0)}")
        if "positions" in result:
            p = result["positions"]
            if isinstance(p, dict) and "error" in p:
                print(f"📊 POSITIONS: ❌ {p['error']}")
            else:
                print(f"📊 POSITIONS: local={p.get('local_base')} exchange={p.get('exchange_base')} diff={p.get('diff')}")
        if "balances" in result:
            b = result["balances"]
            if isinstance(b, dict) and "error" in b:
                print(f"💰 BALANCES: ❌ {b['error']}")
            else:
                print(f"💰 BALANCES: quote={b.get('free_quote')} base={b.get('free_base')}")

        if result.get("discrepancies"):
            print("\n⚠️  DISCREPANCIES:")
            for d in result["discrepancies"]:
                print("  -", d)
        if result.get("actions_taken"):
            print("\n✅ ACTIONS:")
            for a in result["actions_taken"]:
                print("  -", a)

        print("\n" + "=" * 60)
        print("STATUS:", result.get("status", "UNKNOWN"))
        print("=" * 60 + "\n")

    return 0


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
