"""Reconciliation CLI utility.

Located in cli layer - reconciles orders, positions and balances with exchange.
Detects and fixes discrepancies, generates detailed reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Awaitable, Callable

from crypto_ai_bot.app.compose import compose
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Helpers ==============

async def _maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a function that may be sync or async."""
    try:
        result = fn(*args, **kwargs)
    except TypeError:
        # Some storages expose bound methods but raise if kwargs mismatch;
        # just re-raise — this is a real programming error.
        raise
    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):  # type: ignore[arg-type]
        return await result  # type: ignore[func-returns-value]
    return result


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ============== Types ==============

class DiscrepancyType(Enum):
    """Types of discrepancies."""

    MISSING_IN_DB = "missing_in_db"
    MISSING_ON_EXCHANGE = "missing_on_exchange"
    STATUS_MISMATCH = "status_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    PRICE_MISMATCH = "price_mismatch"
    PHANTOM_ORDER = "phantom_order"
    STALE_DATA = "stale_data"


class ReconciliationStatus(Enum):
    """Reconciliation result status."""

    OK = "ok"
    DISCREPANCIES_FOUND = "discrepancies_found"
    DISCREPANCIES_FIXED = "discrepancies_fixed"
    ERROR = "error"


# ============== Data Classes ==============

class Discrepancy:
    """Single discrepancy found during reconciliation."""

    def __init__(
        self,
        type: DiscrepancyType,
        entity: str,  # orders, positions, balances
        id: str,
        expected: Any,
        actual: Any,
        description: str,
        severity: str = "warning",  # info, warning, error
        fixable: bool = False,
    ):
        self.type = type
        self.entity = entity
        self.id = id
        self.expected = expected
        self.actual = actual
        self.description = description
        self.severity = severity
        self.fixable = fixable
        self.fixed = False
        self.fix_result: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "entity": self.entity,
            "id": self.id,
            "expected": str(self.expected) if self.expected is not None else None,
            "actual": str(self.actual) if self.actual is not None else None,
            "description": self.description,
            "severity": self.severity,
            "fixable": self.fixable,
            "fixed": self.fixed,
            "fix_result": self.fix_result,
        }


class ReconciliationReport:
    """Complete reconciliation report."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.timestamp = _now_utc()
        self.trace_id = generate_trace_id()
        self.status = ReconciliationStatus.OK
        self.discrepancies: list[Discrepancy] = []
        self.metrics: dict[str, int] = {
            "orders_checked": 0,
            "positions_checked": 0,
            "balances_checked": 0,
            "discrepancies_found": 0,
            "discrepancies_fixed": 0,
            "duration_ms": 0,
        }

    def add_discrepancy(self, discrepancy: Discrepancy) -> None:
        """Add discrepancy to report."""
        self.discrepancies.append(discrepancy)
        self.metrics["discrepancies_found"] += 1

        if self.status == ReconciliationStatus.OK:
            self.status = ReconciliationStatus.DISCREPANCIES_FOUND

    def mark_fixed(self, discrepancy: Discrepancy, result: Optional[str] = None) -> None:
        """Mark discrepancy as fixed."""
        discrepancy.fixed = True
        discrepancy.fix_result = result
        self.metrics["discrepancies_fixed"] += 1

        # Update status if all fixable discrepancies are fixed
        all_fixable = [d for d in self.discrepancies if d.fixable]
        if all_fixable and all(d.fixed for d in all_fixable):
            self.status = ReconciliationStatus.DISCREPANCIES_FIXED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
            "status": self.status.value,
            "metrics": self.metrics,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
        }


# ============== Reconcilers ==============

class EnhancedOrdersReconciler:
    """Enhanced orders reconciliation with auto-fix."""

    def __init__(self, storage: Any, broker: Any):
        self.storage = storage
        self.broker = broker

    async def reconcile(self, symbol: str, fix: bool = False) -> list[Discrepancy]:
        """Reconcile orders between DB and exchange."""
        discrepancies: list[Discrepancy] = []

        try:
            # Get orders from both sources
            db_orders = await self._get_db_orders(symbol)
            exchange_orders = await self.broker.fetch_open_orders(symbol)

            # Normalize to dict by id
            def _oid(o: Any) -> str:
                return o.id if hasattr(o, "id") else str(o.get("id"))

            db_by_id = {str(o["id"]): o for o in db_orders if "id" in o}
            ex_by_id = {_oid(o): o for o in exchange_orders if _oid(o)}

            # Metrics: how many orders compared (union)
            checked_count = len(set(db_by_id) | set(ex_by_id))

            # Missing on exchange
            for order_id in db_by_id.keys() - ex_by_id.keys():
                disc = Discrepancy(
                    type=DiscrepancyType.MISSING_ON_EXCHANGE,
                    entity="orders",
                    id=order_id,
                    expected="exists",
                    actual="missing",
                    description=f"Order {order_id} in DB but not on exchange",
                    severity="error",
                    fixable=True,
                )
                discrepancies.append(disc)

                if fix and hasattr(self.storage, "orders") and hasattr(self.storage.orders, "update_order_status"):
                    await _maybe_await(
                        self.storage.orders.update_order_status,
                        order_id=order_id,
                        status="canceled",
                        filled=dec("0"),
                        timestamp=_now_utc(),
                    )
                    disc.fixed = True
                    disc.fix_result = "Marked as canceled in DB"

            # Missing in DB
            for order_id in ex_by_id.keys() - db_by_id.keys():
                disc = Discrepancy(
                    type=DiscrepancyType.MISSING_IN_DB,
                    entity="orders",
                    id=order_id,
                    expected="missing",
                    actual="exists",
                    description=f"Order {order_id} on exchange but not in DB",
                    severity="warning",
                    fixable=True,
                )
                discrepancies.append(disc)

                if fix:
                    await self._save_order_to_db(ex_by_id[order_id])
                    disc.fixed = True
                    disc.fix_result = "Added to DB"

            # Status mismatches
            for order_id in db_by_id.keys() & ex_by_id.keys():
                db_order = db_by_id[order_id]
                ex_order = ex_by_id[order_id]

                db_status = db_order.get("status")
                ex_status = ex_order.status if hasattr(ex_order, "status") else ex_order.get("status")

                if db_status != ex_status:
                    disc = Discrepancy(
                        type=DiscrepancyType.STATUS_MISMATCH,
                        entity="orders",
                        id=order_id,
                        expected=db_status,
                        actual=ex_status,
                        description=f"Order {order_id} status mismatch",
                        severity="warning",
                        fixable=True,
                    )
                    discrepancies.append(disc)

                    if fix and hasattr(self.storage, "orders") and hasattr(self.storage.orders, "update_order_status"):
                        filled_val = (
                            ex_order.filled if hasattr(ex_order, "filled") else dec(str(ex_order.get("filled", 0)))
                        )
                        await _maybe_await(
                            self.storage.orders.update_order_status,
                            order_id=order_id,
                            status=ex_status,
                            filled=dec(str(filled_val)),
                            timestamp=_now_utc(),
                        )
                        disc.fixed = True
                        disc.fix_result = f"Updated DB status to {ex_status}"

            # Save metric
            self._last_checked = checked_count  # for suite to pick up

        except Exception as e:
            _log.error(
                "orders_reconciliation_failed",
                exc_info=True,
                extra={"symbol": symbol, "error": str(e)},
            )

            discrepancies.append(
                Discrepancy(
                    type=DiscrepancyType.PHANTOM_ORDER,
                    entity="orders",
                    id="error",
                    expected=None,
                    actual=None,
                    description=f"Reconciliation error: {e}",
                    severity="error",
                    fixable=False,
                )
            )

        return discrepancies

    async def _get_db_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Get open orders from database (tolerant to sync/async repos)."""
        if hasattr(self.storage, "orders") and hasattr(self.storage.orders, "get_open_orders"):
            result = await _maybe_await(self.storage.orders.get_open_orders, symbol)
            if isinstance(result, list):
                return result
        return []

    async def _save_order_to_db(self, order: Any) -> None:
        """Save order to database (tolerant to sync/async repos)."""
        if not (hasattr(self.storage, "orders") and hasattr(self.storage.orders, "save_order")):
            return

        oid = order.id if hasattr(order, "id") else order.get("id")
        coid = order.client_order_id if hasattr(order, "client_order_id") else order.get("client_order_id")
        symbol = order.symbol if hasattr(order, "symbol") else order.get("symbol")
        side = order.side if hasattr(order, "side") else order.get("side")
        typ = order.type if hasattr(order, "type") else order.get("type")
        amount = order.amount if hasattr(order, "amount") else order.get("amount", 0)
        price = order.price if hasattr(order, "price") else order.get("price", 0)
        status = order.status if hasattr(order, "status") else order.get("status")

        await _maybe_await(
            self.storage.orders.save_order,
            order_id=str(oid),
            client_order_id=str(coid) if coid is not None else None,
            symbol=str(symbol),
            side=str(side),
            type=str(typ),
            amount=dec(str(amount or 0)),
            price=dec(str(price or 0)),
            status=str(status),
            timestamp=_now_utc(),
            metadata={},
        )


class EnhancedPositionsReconciler:
    """Enhanced positions reconciliation."""

    def __init__(self, storage: Any, broker: Any):
        self.storage = storage
        self.broker = broker

    async def reconcile(self, symbol: str, fix: bool = False) -> list[Discrepancy]:
        """Reconcile positions between DB and exchange."""
        discrepancies: list[Discrepancy] = []
        tolerance = dec("0.0001")

        try:
            # Storage side (sync/async tolerant)
            db_position = None
            if hasattr(self.storage, "positions") and hasattr(self.storage.positions, "get_position"):
                db_position = await _maybe_await(self.storage.positions.get_position, symbol)

            # Exchange side
            exchange_position = await self.broker.fetch_position(symbol)

            # Normalize db values
            def _d(obj: Any, key: str, default: str = "0") -> Decimal:
                if not obj:
                    return dec(default)
                if isinstance(obj, dict):
                    return dec(str(obj.get(key, default)))
                if hasattr(obj, key):
                    try:
                        return dec(str(getattr(obj, key)))
                    except Exception:
                        return dec(default)
                return dec(default)

            if db_position and not exchange_position:
                disc = Discrepancy(
                    type=DiscrepancyType.MISSING_ON_EXCHANGE,
                    entity="positions",
                    id=symbol,
                    expected="exists",
                    actual="missing",
                    description=f"Position {symbol} in DB but not on exchange",
                    severity="error",
                    fixable=True,
                )
                discrepancies.append(disc)

                if fix and hasattr(self.storage, "positions") and hasattr(self.storage.positions, "close_position"):
                    await _maybe_await(
                        self.storage.positions.close_position,
                        symbol=symbol,
                        exit_price=dec("0"),
                        realized_pnl=dec("0"),
                        timestamp=_now_utc(),
                    )
                    disc.fixed = True
                    disc.fix_result = "Closed in DB"

            elif exchange_position and not db_position:
                disc = Discrepancy(
                    type=DiscrepancyType.MISSING_IN_DB,
                    entity="positions",
                    id=symbol,
                    expected="missing",
                    actual="exists",
                    description=f"Position {symbol} on exchange but not in DB",
                    severity="warning",
                    fixable=True,
                )
                discrepancies.append(disc)

                if fix:
                    await self._save_position_to_db(symbol, exchange_position)
                    disc.fixed = True
                    disc.fix_result = "Added to DB"

            elif db_position and exchange_position:
                db_amount = _d(db_position, "amount")
                ex_amount = _d(exchange_position, "amount")

                if abs(db_amount - ex_amount) > tolerance:
                    disc = Discrepancy(
                        type=DiscrepancyType.AMOUNT_MISMATCH,
                        entity="positions",
                        id=symbol,
                        expected=db_amount,
                        actual=ex_amount,
                        description=f"Position {symbol} amount mismatch",
                        severity="error",
                        fixable=True,
                    )
                    discrepancies.append(disc)

                    if fix:
                        await self._update_position_amount(symbol, ex_amount)
                        disc.fixed = True
                        disc.fix_result = f"Updated DB amount to {ex_amount.normalize()}"

            # Save metric
            self._last_checked = 1  # one symbol's position checked

        except Exception as e:
            _log.error(
                "positions_reconciliation_failed",
                exc_info=True,
                extra={"symbol": symbol, "error": str(e)},
            )

            discrepancies.append(
                Discrepancy(
                    type=DiscrepancyType.PHANTOM_ORDER,
                    entity="positions",
                    id="error",
                    expected=None,
                    actual=None,
                    description=f"Reconciliation error: {e}",
                    severity="error",
                    fixable=False,
                )
            )

        return discrepancies

    async def _save_position_to_db(self, symbol: str, position: Any) -> None:
        """Save position to database (tolerant to sync/async repos)."""
        if not (hasattr(self.storage, "positions") and hasattr(self.storage.positions, "save_position")):
            return

        amount = dec(str(getattr(position, "amount", 0) if hasattr(position, "amount") else position.get("amount", 0)))
        entry_price = dec(
            str(getattr(position, "entry_price", 0) if hasattr(position, "entry_price") else position.get("entry_price", 0))
        )

        await _maybe_await(
            self.storage.positions.save_position,
            symbol=symbol,
            side="long",  # SPOT only supports long; derivatives would carry side from broker
            amount=amount,
            entry_price=entry_price,
            timestamp=_now_utc(),
        )

    async def _update_position_amount(self, symbol: str, amount: Decimal) -> None:
        """Update position amount in database (best-effort)."""
        if hasattr(self.storage, "positions") and hasattr(self.storage.positions, "update_amount"):
            await _maybe_await(self.storage.positions.update_amount, symbol=symbol, amount=dec(str(amount)))
        else:
            # If repo has save_position, overwrite record
            await self._save_position_to_db(symbol, {"amount": amount, "entry_price": "0"})


class EnhancedBalancesReconciler:
    """Enhanced balances reconciliation."""

    def __init__(self, storage: Any, broker: Any):
        self.storage = storage
        self.broker = broker

    async def reconcile(self, symbol: str) -> dict[str, Any]:
        """Reconcile balances with exchange (read-only; flags inconsistencies)."""
        result: dict[str, Any] = {
            "timestamp": _now_utc().isoformat(),
            "balances": {},
            "discrepancies": [],
        }

        try:
            balances = await self.broker.fetch_balance()

            # Parse symbol to get base and quote currencies
            base_currency, quote_currency = ("BTC", "USDT")
            parts = str(symbol).split("/")
            if len(parts) == 2:
                base_currency, quote_currency = parts[0], parts[1]

            def _extract(bal: Any) -> tuple[Decimal, Decimal, Decimal]:
                # Support objects with attributes OR dicts
                if hasattr(bal, "free") or hasattr(bal, "used") or hasattr(bal, "total"):
                    fr = dec(str(getattr(bal, "free", 0) or 0))
                    us = dec(str(getattr(bal, "used", 0) or 0))
                    to = dec(str(getattr(bal, "total", fr + us) or (fr + us)))
                    return fr, us, to
                if isinstance(bal, dict):
                    fr = dec(str(bal.get("free", 0) or 0))
                    us = dec(str(bal.get("used", 0) or 0))
                    to = dec(str(bal.get("total", fr + us) or (fr + us)))
                    return fr, us, to
                # Primitive
                val = dec(str(bal or 0))
                return val, dec("0"), val

            checked = 0
            for currency in [base_currency, quote_currency]:
                if currency in balances:
                    free, used, total = _extract(balances[currency])
                    result["balances"][currency] = {
                        "free": float(free),
                        "used": float(used),
                        "total": float(total),
                    }
                    checked += 1

                    if (free + used - total).copy_abs() > dec("0.00001"):
                        result["discrepancies"].append(
                            {
                                "currency": currency,
                                "issue": "free + used != total",
                                "free": float(free),
                                "used": float(used),
                                "total": float(total),
                            }
                        )

            result["checked"] = checked

        except Exception as e:
            _log.error(
                "balances_reconciliation_failed",
                exc_info=True,
                extra={"symbol": symbol, "error": str(e)},
            )
            result["error"] = str(e)

        return result


# ============== Main Reconciler ==============

class ReconciliationSuite:
    """Complete reconciliation suite."""

    def __init__(self, container: Any):
        self.container = container
        self.storage = container.storage
        self.broker = container.broker
        self.orders_reconciler = EnhancedOrdersReconciler(self.storage, self.broker)
        self.positions_reconciler = EnhancedPositionsReconciler(self.storage, self.broker)
        self.balances_reconciler = EnhancedBalancesReconciler(self.storage, self.broker)

    async def run(self, symbol: str, fix: bool = False, components: Optional[list[str]] = None) -> ReconciliationReport:
        """Run complete reconciliation."""
        report = ReconciliationReport(symbol)
        started = _now_utc()

        # Default to all components
        if not components:
            components = ["orders", "positions", "balances"]

        _log.info(
            "reconciliation_started",
            extra={"symbol": symbol, "fix": fix, "components": components, "trace_id": report.trace_id},
        )

        try:
            # Reconcile orders
            if "orders" in components:
                order_discrepancies = await self.orders_reconciler.reconcile(symbol, fix)
                for disc in order_discrepancies:
                    report.add_discrepancy(disc)
                    if disc.fixed:
                        report.mark_fixed(disc)
                report.metrics["orders_checked"] = getattr(self.orders_reconciler, "_last_checked", 0)

            # Reconcile positions
            if "positions" in components:
                position_discrepancies = await self.positions_reconciler.reconcile(symbol, fix)
                for disc in position_discrepancies:
                    report.add_discrepancy(disc)
                    if disc.fixed:
                        report.mark_fixed(disc)
                report.metrics["positions_checked"] = getattr(self.positions_reconciler, "_last_checked", 0)

            # Reconcile balances
            if "balances" in components:
                balance_result = await self.balances_reconciler.reconcile(symbol)
                if balance_result.get("discrepancies"):
                    for bal_disc in balance_result["discrepancies"]:
                        disc = Discrepancy(
                            type=DiscrepancyType.AMOUNT_MISMATCH,
                            entity="balances",
                            id=str(bal_disc.get("currency", "?")),
                            expected=None,
                            actual=None,
                            description=str(bal_disc.get("issue", "inconsistency")),
                            severity="warning",
                            fixable=False,
                        )
                        report.add_discrepancy(disc)
                report.metrics["balances_checked"] = int(balance_result.get("checked", 0))

        except Exception as e:
            _log.error(
                "reconciliation_suite_failed",
                exc_info=True,
                extra={"symbol": symbol, "error": str(e), "trace_id": report.trace_id},
            )
            report.status = ReconciliationStatus.ERROR

        # Duration
        duration_ms = int((_now_utc() - started).total_seconds() * 1000)
        report.metrics["duration_ms"] = duration_ms

        _log.info(
            "reconciliation_completed",
            extra={
                "symbol": symbol,
                "status": report.status.value,
                "discrepancies_found": report.metrics["discrepancies_found"],
                "discrepancies_fixed": report.metrics["discrepancies_fixed"],
                "duration_ms": duration_ms,
                "trace_id": report.trace_id,
            },
        )

        return report


# ============== CLI Commands ==============

def format_report(report: ReconciliationReport, fmt: str = "text") -> str:
    """Format reconciliation report for output."""
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2)

    if fmt == "text":
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("RECONCILIATION REPORT")
        lines.append("=" * 60)
        lines.append(f"Symbol: {report.symbol}")
        lines.append(f"Status: {report.status.value.upper()}")
        lines.append(f"Timestamp: {report.timestamp.isoformat()}")
        lines.append(f"Trace ID: {report.trace_id}")
        lines.append("")

        # Metrics
        lines.append("METRICS:")
        for key in ["orders_checked", "positions_checked", "balances_checked", "discrepancies_found", "discrepancies_fixed", "duration_ms"]:
            val = report.metrics.get(key, 0)
            lines.append(f"  {key}: {val}")
        lines.append("")

        # Discrepancies
        if report.discrepancies:
            lines.append(f"DISCREPANCIES ({len(report.discrepancies)} found):")
            for i, disc in enumerate(report.discrepancies, 1):
                status_icon = "✅" if disc.fixed else ("❌" if disc.severity == "error" else "⚠️")
                lines.append(f"\n{i}. {status_icon} [{disc.severity.upper()}] {disc.entity}/{disc.id}")
                lines.append(f"   Type: {disc.type.value}")
                lines.append(f"   Description: {disc.description}")
                if disc.expected is not None:
                    lines.append(f"   Expected: {disc.expected}")
                if disc.actual is not None:
                    lines.append(f"   Actual: {disc.actual}")
                if disc.fixed:
                    lines.append(f"   ✅ FIXED: {disc.fix_result}")
        else:
            lines.append("✅ No discrepancies found")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # Fallback
    return str(report.to_dict())


# ============== CLI Entry Point ==============

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="cab-reconcile",
        description="Reconcile orders, positions and balances with exchange",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check all components
  cab-reconcile

  # Check and auto-fix discrepancies
  cab-reconcile --fix

  # Check specific symbol
  cab-reconcile --symbol ETH/USDT

  # Check only orders
  cab-reconcile --components orders

  # Output as JSON
  cab-reconcile --format json
        """,
    )

    parser.add_argument("--symbol", help="Trading symbol (default from settings)")
    parser.add_argument("--fix", action="store_true", help="Automatically fix discrepancies")
    parser.add_argument(
        "--components",
        nargs="+",
        choices=["orders", "positions", "balances"],
        help="Components to reconcile (default: all)",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--output", help="Output file (default: stdout)")

    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    container = None
    try:
        # Create container
        container = await compose()

        # Get symbol
        symbol = args.symbol or canonical(getattr(container.settings, "SYMBOL", "BTC/USDT"))

        # Create reconciliation suite
        suite = ReconciliationSuite(container)

        # Run reconciliation
        report = await suite.run(symbol=symbol, fix=args.fix, components=args.components)

        # Format output
        output = format_report(report, args.format)

        # Write output
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Report saved to: {args.output}")
        else:
            print(output)

        # Exit codes
        if report.status in (ReconciliationStatus.OK, ReconciliationStatus.DISCREPANCIES_FIXED):
            return 0
        if report.status == ReconciliationStatus.DISCREPANCIES_FOUND:
            return 1
        return 2

    except Exception as e:
        _log.error("reconciliation_error", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        return 2

    finally:
        if container is not None:
            try:
                await container.stop()
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
