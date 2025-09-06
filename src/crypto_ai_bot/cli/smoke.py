"""Smoke test CLI utility.

Located in cli layer - performs quick system health check.
Verifies imports, connections, and basic functionality.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Test Result Classes ==============

class TestResult:
    """Single test result."""

    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category
        self.passed = False
        self.message = ""
        self.duration_ms = 0
        self.error: Optional[Exception] = None

    def mark_passed(self, message: str = "OK") -> None:
        """Mark test as passed."""
        self.passed = True
        self.message = message

    def mark_failed(self, message: str, error: Optional[Exception] = None) -> None:
        """Mark test as failed."""
        self.passed = False
        self.message = message
        self.error = error

    def emoji(self) -> str:
        """Get status emoji."""
        return "✅" if self.passed else "❌"


class SmokeTestReport:
    """Complete smoke test report."""

    def __init__(self):
        self.trace_id = generate_trace_id()
        self.timestamp = datetime.now(timezone.utc)
        self.results: list[TestResult] = []
        self.total_duration_ms = 0

    def add_result(self, result: TestResult) -> None:
        """Add test result."""
        self.results.append(result)

    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return all(r.passed for r in self.results)

    def get_summary(self) -> dict[str, int | float]:
        """Get summary statistics."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": (passed / total * 100) if total > 0 else 0.0,
        }

    def format_text(self, verbose: bool = False) -> str:
        """Format report as text."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("SMOKE TEST REPORT")
        lines.append("=" * 60)
        lines.append(f"Timestamp: {self.timestamp.isoformat()}")
        lines.append(f"Trace ID: {self.trace_id}")
        lines.append("")

        # Group results by category
        categories: dict[str, list[TestResult]] = defaultdict(list)
        for result in self.results:
            categories[result.category].append(result)

        # Print by category
        for category, results in categories.items():
            lines.append(f"{category.upper()}:")
            for r in results:
                status = r.emoji()
                duration = f"({r.duration_ms}ms)" if r.duration_ms > 0 else ""
                lines.append(f"  {status} {r.name} {duration}")
                if verbose or not r.passed:
                    lines.append(f"     {r.message}")
                    if r.error and verbose:
                        lines.append(f"     Error: {r.error!r}")
            lines.append("")

        # Summary
        summary = self.get_summary()
        lines.append("SUMMARY:")
        lines.append(f"  Total: {summary['total']}")
        lines.append(f"  Passed: {summary['passed']}")
        lines.append(f"  Failed: {summary['failed']}")
        lines.append(f"  Success Rate: {summary['success_rate']:.1f}%")
        lines.append(f"  Duration: {self.total_duration_ms}ms")
        lines.append("")

        # Overall status
        lines.append("✅ ALL TESTS PASSED" if self.all_passed() else "❌ SOME TESTS FAILED")
        lines.append("=" * 60)

        return "\n".join(lines)


# ============== Test Functions ==============

class SmokeTests:
    """Collection of smoke tests."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.report = SmokeTestReport()

    async def test_imports(self) -> None:
        """Test critical imports."""
        critical_modules = [
            # App layer
            ("crypto_ai_bot.app.server", "FastAPI server"),
            ("crypto_ai_bot.app.compose", "DI container"),
            ("crypto_ai_bot.app.telegram_bot", "Telegram bot"),

            # Application layer
            ("crypto_ai_bot.core.application.orchestrator", "Orchestrator"),
            ("crypto_ai_bot.core.application.ports", "Ports/Contracts"),
            ("crypto_ai_bot.core.application.events_topics", "Event topics"),

            # Domain layer
            ("crypto_ai_bot.core.domain.risk.manager", "Risk manager"),
            ("crypto_ai_bot.core.domain.strategies.strategy_manager", "Strategy manager"),

            # Infrastructure layer
            ("crypto_ai_bot.core.infrastructure.brokers.factory", "Broker factory"),
            ("crypto_ai_bot.core.infrastructure.events.bus", "Event bus"),
            ("crypto_ai_bot.core.infrastructure.storage.facade", "Storage"),
            ("crypto_ai_bot.core.infrastructure.settings", "Settings"),

            # Utils
            ("crypto_ai_bot.utils.decimal", "Decimal utils"),
            ("crypto_ai_bot.utils.pnl", "PnL calculator"),
        ]

        for module_name, description in critical_modules:
            result = TestResult(f"Import {description}", "imports")
            start = time.time()

            try:
                importlib.import_module(module_name)
                result.mark_passed(f"Module {module_name} imported")

            except ImportError as e:
                result.mark_failed(f"Failed to import {module_name}", e)

            except Exception as e:
                result.mark_failed(f"Unexpected error importing {module_name}", e)

            result.duration_ms = int((time.time() - start) * 1000)
            self.report.add_result(result)

    async def test_database(self) -> None:
        """Test database connectivity."""
        result = TestResult("Database connection", "database")
        start = time.time()

        try:
            from crypto_ai_bot.core.infrastructure.settings import get_settings

            settings = get_settings()
            db_path = Path(getattr(settings, "DB_PATH", "./data/trader.sqlite3"))

            if not db_path.exists():
                # Ensure directory exists
                db_path.parent.mkdir(parents=True, exist_ok=True)

            # Test connection
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT sqlite_version()")
            version = cursor.fetchone()[0]
            conn.close()

            result.mark_passed(f"SQLite {version}, DB: {db_path}")

        except Exception as e:
            result.mark_failed("Database connection failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_broker(self) -> None:
        """Test broker initialization."""
        result = TestResult("Broker initialization", "broker")
        start = time.time()

        try:
            from crypto_ai_bot.core.infrastructure.brokers.factory import make_broker
            from crypto_ai_bot.core.infrastructure.settings import get_settings

            settings = get_settings()
            mode = getattr(settings, "MODE", "paper")
            exchange = getattr(settings, "EXCHANGE", "gateio")

            broker = make_broker(mode=mode, exchange=exchange, settings=settings)

            # For paper mode, just check it's created
            if mode == "paper":
                result.mark_passed(f"Paper broker created for {exchange}")
            else:
                # For live mode, could test connection
                result.mark_passed(f"Live broker created for {exchange}")

            # avoid 'unused' warning
            _ = broker

        except Exception as e:
            result.mark_failed("Broker initialization failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_event_bus(self) -> None:
        """Test event bus."""
        result = TestResult("Event bus", "events")
        start = time.time()

        try:
            from crypto_ai_bot.core.infrastructure.events.bus import AsyncEventBus

            bus = AsyncEventBus()
            await bus.start()
            received: list[dict[str, Any]] = []

            async def handler(payload: dict[str, Any]) -> None:
                received.append(payload)

            try:
                await bus.subscribe("test.topic", handler)
                await bus.publish("test.topic", {"test": "data"})
                # Give it a moment to process
                await asyncio.sleep(0.2)
            finally:
                await bus.stop()

            if received:
                result.mark_passed("Event bus working")
            else:
                result.mark_failed("Event not received")

        except Exception as e:
            result.mark_failed("Event bus test failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_http_endpoint(self, url: str, timeout: float) -> None:
        """Test HTTP endpoint."""
        result = TestResult(f"HTTP {url}", "network")
        start = time.time()

        try:
            # outer watchdog to guarantee exit even if aget misbehaves
            async with asyncio.timeout(timeout + 2.0):
                resp = await aget(url, hard_timeout=timeout)

            if resp.status_code == 200:
                result.mark_passed("HTTP 200 OK")
            else:
                # try to include small body preview if present
                body_preview = ""
                try:
                    txt = getattr(resp, "text", "") or ""
                    if txt:
                        body_preview = f" | body: {txt[:120]}"
                except Exception:
                    pass
                result.mark_failed(f"HTTP {resp.status_code}{body_preview}")

        except asyncio.TimeoutError:
            result.mark_failed(f"Timeout after {timeout}s")

        except Exception as e:
            result.mark_failed("HTTP request failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_settings(self) -> None:
        """Test settings loading."""
        result = TestResult("Settings", "configuration")
        start = time.time()

        try:
            from crypto_ai_bot.core.infrastructure.settings import get_settings

            settings = get_settings()

            # Check critical settings
            mode = getattr(settings, "MODE", None)
            exchange = getattr(settings, "EXCHANGE", None)

            if not mode:
                result.mark_failed("MODE not configured")
            elif not exchange:
                result.mark_failed("EXCHANGE not configured")
            else:
                result.mark_passed(f"Mode: {mode}, Exchange: {exchange}")

        except Exception as e:
            result.mark_failed("Settings loading failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_risk_manager(self) -> None:
        """Test risk manager initialization."""
        result = TestResult("Risk Manager", "risk")
        start = time.time()

        try:
            from crypto_ai_bot.core.domain.risk.manager import RiskManager, RiskConfig
            from crypto_ai_bot.core.infrastructure.settings import get_settings

            settings = get_settings()
            config = RiskConfig.from_settings(settings)
            risk_manager = RiskManager(config)

            rules_count = len(risk_manager.rules) if hasattr(risk_manager, "rules") else 0

            if rules_count > 0:
                result.mark_passed(f"{rules_count} risk rules loaded")
            else:
                result.mark_failed("No risk rules loaded")

            _ = risk_manager

        except Exception as e:
            result.mark_failed("Risk manager initialization failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def test_full_cycle(self) -> None:
        """Test minimal trading cycle."""
        result = TestResult("Trading cycle", "integration")
        start = time.time()

        try:
            from crypto_ai_bot.app.compose import compose

            container = await compose()
            try:
                if hasattr(container, "orchestrators"):
                    orch_count = len(container.orchestrators)
                    result.mark_passed(f"{orch_count} orchestrators created")
                else:
                    result.mark_failed("No orchestrators created")
            finally:
                # ensure cleanup
                await container.stop()

        except Exception as e:
            result.mark_failed("Full cycle test failed", e)

        result.duration_ms = int((time.time() - start) * 1000)
        self.report.add_result(result)

    async def run_all(
        self,
        test_http: bool = False,
        http_url: Optional[str] = None,
        http_timeout: float = 5.0,
        quick: bool = False,
    ) -> SmokeTestReport:
        """Run all smoke tests."""
        start = time.time()

        _log.info("smoke_test_started", extra={"trace_id": self.report.trace_id})

        # Core checks
        await self.test_imports()
        await self.test_settings()
        await self.test_database()
        await self.test_broker()
        await self.test_event_bus()
        await self.test_risk_manager()

        # Integration
        if not quick:
            await self.test_full_cycle()

        # Optional HTTP
        if test_http and http_url:
            await self.test_http_endpoint(http_url, http_timeout)

        # Duration
        self.report.total_duration_ms = int((time.time() - start) * 1000)

        _log.info(
            "smoke_test_completed",
            extra={
                "trace_id": self.report.trace_id,
                "passed": self.report.all_passed(),
                "summary": self.report.get_summary(),
            },
        )

        return self.report


# ============== CLI Entry Point ==============

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="cab-smoke",
        description="Smoke test for crypto-ai-bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick smoke test
  cab-smoke

  # Full test with HTTP endpoint
  cab-smoke --url http://localhost:8000/health

  # Verbose output
  cab-smoke --verbose

  # Quick test (skip integration)
  cab-smoke --quick
        """,
    )

    parser.add_argument(
        "--url",
        default=os.getenv("HEALTH_URL", ""),
        help="Optional health endpoint to test",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("HTTP_TIMEOUT_SEC", "5")),
        help="HTTP timeout in seconds",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip integration tests",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    tests = SmokeTests(verbose=args.verbose)
    report = await tests.run_all(
        test_http=bool(args.url),
        http_url=args.url,
        http_timeout=args.timeout,
        quick=args.quick,
    )

    # Output report
    if args.json:
        import json

        output = {
            "trace_id": report.trace_id,
            "timestamp": report.timestamp.isoformat(),
            "passed": report.all_passed(),
            "summary": report.get_summary(),
            "results": [
                {
                    "name": r.name,
                    "category": r.category,
                    "passed": r.passed,
                    "message": r.message,
                    "duration_ms": r.duration_ms,
                    "error": (repr(r.error) if r.error else None),
                }
                for r in report.results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(report.format_text(verbose=args.verbose))

    # Return exit code
    return 0 if report.all_passed() else 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        _log.error("smoke_test_error", exc_info=True)
        print(f"❌ Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
