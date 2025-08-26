#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.app.compose import build_container
from crypto_ai_bot.core.reconciliation.orders import OrdersReconciler
from crypto_ai_bot.core.reconciliation.positions import PositionsReconciler
from crypto_ai_bot.core.reconciliation.balances import BalancesReconciler
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

log = get_logger("reconciler")


class ManualReconciler:
    def __init__(self, container) -> None:
        self.c = container
        self.symbol = container.settings.SYMBOL

    async def run_full(self, auto_fix: bool = False) -> Dict[str, Any]:
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
            orders_rec = OrdersReconciler(self.c.broker, self.symbol)
            report["orders"] = await orders_rec.run_once()
            if report["orders"].get("open_orders", 0) > 0:
                report["discrepancies"].append(
                    {
                        "type": "hanging_orders",
                        "count": report["orders"]["open_orders"],
                        "ids": report["orders"].get("ids", [])[:10],
                    }
                )
        except Exception as exc:
            report["orders"] = {"error": str(exc)}
            log.error("orders_reconciliation_failed", extra={"error": str(exc)})

        # 2) Positions
        try:
            pos_rec = PositionsReconciler(storage=self.c.storage, broker=self.c.broker, symbol=self.symbol)
            report["positions"] = await pos_rec.run_once()

            local = Decimal(str(report["positions"].get("local_base", "0")))
            exchange = Decimal(str(report["positions"].get("exchange_base", "0")))
            diff = abs(exchange - local)

            if diff > Decimal("0.00000001"):
                report["discrepancies"].append(
                    {"type": "position_mismatch", "local": str(local), "exchange": str(exchange), "diff": str(diff)}
                )
                if auto_fix:
                    # коррекция локальной позиции под биржу
                    self.c.storage.positions.set_base_qty(self.symbol, exchange)
                    report["actions_taken"].append({"action": "position_corrected", "old": str(local), "new": str(exchange)})
        except Exception as exc:
            report["positions"] = {"error": str(exc)}
            log.error("positions_reconciliation_failed", extra={"error": str(exc)})

        # 3) Balances
        try:
            bal_rec = BalancesReconciler(self.c.broker, self.symbol)
            report["balances"] = await bal_rec.run_once()
        except Exception as exc:
            report["balances"] = {"error": str(exc)}
            log.error("balances_reconciliation_failed", extra={"error": str(exc)})

        # 4) Consistency checks
        try:
            checks = await self._consistency_checks()
            report["consistency"] = checks
            # сигнализируем о критичных несоответствиях
            if checks.get("duplicate_orders", []):
                report["discrepancies"].append({"type": "duplicate_client_order_id", "count": len(checks["duplicate_orders"])})
        except Exception as exc:
            report["consistency_error"] = str(exc)

        report["status"] = "OK" if not report["discrepancies"] else "DISCREPANCIES_FOUND"
        report["requires_action"] = bool(report["discrepancies"])
        return report

    async def _consistency_checks(self) -> Dict[str, Any]:
        conn = self.c.storage.conn
        res: Dict[str, Any] = {}

        # 1) позиция как сумма сделок
        try:
            q = """
            SELECT side, SUM(amount) AS total
            FROM trades
            WHERE symbol = ?
            GROUP BY side
            """
            rows = conn.execute(q, (self.symbol,)).fetchall()
            buys = sum(float(r[1]) for r in rows if r[0] == "buy")
            sells = sum(float(r[1]) for r in rows if r[0] == "sell")
            calc_pos = buys - sells
            stored_pos = float(self.c.storage.positions.get_base_qty(self.symbol) or 0.0)
            res["position_consistency"] = {
                "calculated": calc_pos,
                "stored": stored_pos,
                "match": abs(calc_pos - stored_pos) < 1e-8,
            }
        except Exception:
            # таблицы может не быть в ранних версиях схемы
            res["position_consistency"] = {"skipped": True}

        # 2) просроченные idempotency-ключи
        try:
            expired = conn.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE expires_at_ms < ?",
                (now_ms(),),
            ).fetchone()[0]
            res["expired_idempotency_keys"] = int(expired)
        except Exception:
            res["expired_idempotency_keys"] = 0

        # 3) дубликаты client_order_id
        try:
            rows = conn.execute(
                """
                SELECT client_order_id, COUNT(*) AS cnt
                FROM trades
                WHERE client_order_id IS NOT NULL
                GROUP BY client_order_id
                HAVING cnt > 1
                """
            ).fetchall()
            res["duplicate_orders"] = [{"client_order_id": r[0], "count": int(r[1])} for r in rows]
        except Exception:
            res["duplicate_orders"] = []

        return res


async def _run(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Manual reconciliation tool")
    ap.add_argument("--symbol", help="Override symbol from settings")
    ap.add_argument("--auto-fix", action="store_true", help="Auto-fix discrepancies (local position)")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--check-only", action="store_true", help="Only run consistency checks")
    args = ap.parse_args(argv)

    c = build_container()
    if args.symbol:
        c.settings.SYMBOL = args.symbol

    rec = ManualReconciler(c)

    if args.check_only:
        result = await rec._consistency_checks()
    else:
        result = await rec.run_full(auto_fix=args.auto_fix)

    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\n" + "=" * 60)
        print(f"RECONCILIATION REPORT - {result.get('symbol', 'UNKNOWN')}")
        print("=" * 60)

        # Orders
        o = result.get("orders", {})
        print("\n📦 ORDERS:")
        if "error" in o:
            print(f"   ❌ Error: {o['error']}")
        else:
            print(f"   Open orders: {o.get('open_orders', 0)}")
            if o.get("ids"):
                print(f"   IDs: {', '.join(o['ids'])}")

        # Positions
        p = result.get("positions", {})
        print("\n📊 POSITIONS:")
        if "error" in p:
            print(f"   ❌ Error: {p['error']}")
        else:
            print(f"   Local:    {p.get('local_base', 'N/A')}")
            print(f"   Exchange: {p.get('exchange_base', 'N/A')}")
            print(f"   Diff:     {p.get('diff', 'N/A')}")

        # Balances
        b = result.get("balances", {})
        print("\n💰 BALANCES:")
        if "error" in b:
            print(f"   ❌ Error: {b['error']}")
        else:
            print(f"   Free quote: {b.get('free_quote', 'N/A')}")
            print(f"   Free base:  {b.get('free_base', 'N/A')}")

        # Discrepancies
        if result.get("discrepancies"):
            print("\n⚠️  DISCREPANCIES:")
            for d in result["discrepancies"]:
                print(f"   - {d['type']}: {d}")

        # Consistency
        cc = result.get("consistency", {})
        if cc:
            print("\n🧪 CONSISTENCY:")
            print(f"   Position calc vs stored: {cc.get('position_consistency')}")
            print(f"   Expired idempotency keys: {cc.get('expired_idempotency_keys')}")
            if cc.get("duplicate_orders"):
                print(f"   Duplicates: {len(cc['duplicate_orders'])}")

        # Final
        print("\n" + "=" * 60)
        print(f"STATUS: {result.get('status', 'OK')}")
        if result.get("requires_action"):
            print("⚠️  MANUAL INTERVENTION REQUIRED")
        else:
            print("✅ All systems reconciled successfully")
        print("=" * 60 + "\n")

    # аккуратное закрытие коннекта
    try:
        c.storage.conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
