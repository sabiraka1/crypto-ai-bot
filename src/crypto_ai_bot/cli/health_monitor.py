"""Health monitoring CLI utility.

Located in cli layer - monitors system health via HTTP endpoint.
Supports oneshot checks and continuous monitoring with alerts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol

from crypto_ai_bot.utils.http_client import aget
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.trace import generate_trace_id

_log = get_logger(__name__)


# ============== Health Status ==============

class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "HealthStatus":
        """Parse status from health response."""
        status = str(data.get("status", "")).lower()

        if status in {"healthy", "ok"}:
            return cls.HEALTHY
        if status in {"degraded", "warning"}:
            return cls.DEGRADED
        if status in {"unhealthy", "error"}:
            return cls.UNHEALTHY
        return cls.UNKNOWN

    def exit_code(self) -> int:
        """Get exit code for status."""
        return {
            self.HEALTHY: 0,
            self.DEGRADED: 1,
            self.UNHEALTHY: 2,
            self.UNKNOWN: 3,
        }[self]

    def emoji(self) -> str:
        """Get emoji for status."""
        return {
            self.HEALTHY: "✅",
            self.DEGRADED: "⚠️",
            self.UNHEALTHY: "❌",
            self.UNKNOWN: "❓",
        }[self]


# ============== Alert Integration ==============

class AlertClient(Protocol):
    async def notify(self, status: HealthStatus, message: str) -> None: ...


class HealthAlertNotifier:
    """Send alerts on health status changes."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("HEALTH_ALERT_WEBHOOK")
        self.enabled = bool(self.webhook_url)

    async def notify(self, status: HealthStatus, message: str) -> None:
        """Send alert notification."""
        if not self.enabled:
            return

        try:
            payload = {
                "status": status.value,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": self._get_severity(status),
            }

            await aget(
                self.webhook_url,  # type: ignore[arg-type]
                method="POST",
                json=payload,
                hard_timeout=5.0,
            )
        except Exception as e:
            _log.error("health_alert_failed", exc_info=True, extra={"error": str(e)})

    def _get_severity(self, status: HealthStatus) -> str:
        """Map status to alert severity."""
        return {
            HealthStatus.HEALTHY: "info",
            HealthStatus.DEGRADED: "warning",
            HealthStatus.UNHEALTHY: "critical",
            HealthStatus.UNKNOWN: "critical",
        }[status]


# ============== Health Monitor ==============

class HealthMonitor:
    """Monitor system health via HTTP endpoint."""

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        interval: float = 5.0,
        verbose: bool = False,
        notifier: Optional[AlertClient] = None,
        clear_screen: bool = True,
    ):
        self.url = url
        self.timeout = timeout
        self.interval = max(0.5, interval)
        self.verbose = verbose
        self.notifier = notifier
        self.clear_screen = clear_screen

        # State tracking
        self._last_status: Optional[HealthStatus] = None
        self._consecutive_failures: int = 0
        self._start_time = datetime.now(timezone.utc)
        self._last_lines_printed: int = 0

        # Statistics
        self._stats = {
            "checks": 0,
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "failures": 0,
        }

    async def _fetch_health(self) -> tuple[HealthStatus, dict[str, Any]]:
        """Fetch health status from endpoint."""
        trace_id = generate_trace_id()
        self._stats["checks"] += 1

        try:
            # aget уже имеет hard_timeout; добавляем внешний safety-таймаут
            async with asyncio.timeout(self.timeout + 5):
                resp = await aget(self.url, hard_timeout=self.timeout)

            # Parse response
            if resp.status_code == 200:
                data = self._parse_response(resp)
                status = HealthStatus.from_response(data)
                self._consecutive_failures = 0

                # Update stats
                if status == HealthStatus.HEALTHY:
                    self._stats["healthy"] += 1
                elif status == HealthStatus.DEGRADED:
                    self._stats["degraded"] += 1
                else:
                    self._stats["unhealthy"] += 1

                return status, data

            # Non-200 response
            self._consecutive_failures += 1
            self._stats["failures"] += 1
            _log.warning(
                "health_check_http_error",
                extra={"url": self.url, "status_code": resp.status_code, "trace_id": trace_id},
            )
            return HealthStatus.UNHEALTHY, {
                "status": "unhealthy",
                "error": f"HTTP {resp.status_code}",
                "trace_id": trace_id,
            }

        except asyncio.TimeoutError:
            self._consecutive_failures += 1
            self._stats["failures"] += 1
            _log.error(
                "health_check_timeout",
                extra={"url": self.url, "timeout": self.timeout, "trace_id": trace_id},
            )
            return HealthStatus.UNKNOWN, {"status": "unknown", "error": "Timeout", "trace_id": trace_id}

        except Exception as e:
            self._consecutive_failures += 1
            self._stats["failures"] += 1
            _log.error(
                "health_check_failed",
                exc_info=True,
                extra={"url": self.url, "error": str(e), "trace_id": trace_id},
            )
            return HealthStatus.UNKNOWN, {"status": "unknown", "error": str(e), "trace_id": trace_id}

    def _parse_response(self, resp: Any) -> dict[str, Any]:
        """Parse HTTP response to dict."""
        # Try JSON (even if content-type is missing/incorrect)
        try:
            return resp.json()
        except Exception:
            pass

        # Fallback to text
        return {
            "status": "healthy" if resp.status_code == 200 else "unhealthy",
            "raw": (getattr(resp, "text", "") or "")[:1000],  # Limit size
        }

    def _format_output(self, status: HealthStatus, data: dict[str, Any]) -> str:
        """Format health data for output."""
        if self.verbose:
            # Full JSON output
            return json.dumps(data, ensure_ascii=False, indent=2)

        # Compact output
        lines: list[str] = []

        # Status line
        timestamp = datetime.now(timezone.utc).isoformat()
        lines.append(f"[{timestamp}] {status.emoji()} Status: {status.value.upper()}")

        # Components if available
        if isinstance(data.get("components"), dict):
            lines.append("\nComponents:")
            for name, comp_status in data["components"].items():
                emoji = "✅" if comp_status == "healthy" else "❌"
                lines.append(f"  {emoji} {name}: {comp_status}")

        # Metrics if available
        if isinstance(data.get("metrics"), dict):
            lines.append("\nMetrics:")
            for key, value in data["metrics"].items():
                lines.append(f"  {key}: {value}")

        # Errors
        if error := data.get("error"):
            lines.append(f"\n❌ Error: {error}")

        # Stats in watch mode
        if self._stats["checks"] >= 1:
            lines.append(f"\n📊 Stats: {self._format_stats()}")

        return "\n".join(lines)

    def _format_stats(self) -> str:
        """Format statistics."""
        total = self._stats["checks"]
        if total == 0:
            return "No checks yet"

        healthy_pct = (self._stats["healthy"] / total) * 100
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        uptime_min = uptime / 60

        return (
            f"Checks: {total}, "
            f"Healthy: {healthy_pct:.1f}%, "
            f"Failures: {self._stats['failures']}, "
            f"Uptime: {uptime_min:.1f}m"
        )

    async def check_once(self) -> int:
        """Perform single health check."""
        status, data = await self._fetch_health()

        # Print output
        output = self._format_output(status, data)
        print(output)

        # Return exit code
        return status.exit_code()

    async def watch(self) -> None:
        """Continuously monitor health."""
        print(f"🔍 Monitoring health: {self.url}")
        print(f"   Interval: {self.interval}s, Timeout: {self.timeout}s")
        print("   Press Ctrl+C to stop\n")

        while True:
            status, data = await self._fetch_health()

            # Notify on status changes
            if self._last_status and status != self._last_status:
                await self._on_status_change(self._last_status, status)

            # Print current status
            output = self._format_output(status, data)

            # Clear previous lines if not verbose
            if self.clear_screen and not self.verbose and self._last_lines_printed:
                # Move cursor up and clear
                print(f"\033[{self._last_lines_printed}A\033[J", end="")

            print(output)
            self._last_lines_printed = output.count("\n") + 1

            # Warning on consecutive failures
            if self._consecutive_failures >= 3:
                print(f"\n⚠️ WARNING: {self._consecutive_failures} consecutive failures!")

            self._last_status = status

            # Wait for next check
            await asyncio.sleep(self.interval)

    async def _on_status_change(self, old: HealthStatus, new: HealthStatus) -> None:
        """Handle status change."""
        timestamp = datetime.now(timezone.utc).isoformat()

        if new == HealthStatus.HEALTHY and old != HealthStatus.HEALTHY:
            msg = f"System recovered! Status: {old.value} → {new.value}"
            print(f"\n✅ [{timestamp}] {msg}")
            if self.notifier:
                await self.notifier.notify(new, msg)

        elif new != HealthStatus.HEALTHY and (old == HealthStatus.HEALTHY or old is None):
            msg = f"System degraded! Status: {old.value if old else 'unknown'} → {new.value}"
            print(f"\n⚠️ [{timestamp}] {msg}")
            if self.notifier:
                await self.notifier.notify(new, msg)

        else:
            msg = f"Status changed: {old.value if old else 'unknown'} → {new.value}"
            print(f"\n📊 [{timestamp}] {msg}")
            if self.notifier:
                await self.notifier.notify(new, msg)


# ============== CLI Entry Point ==============

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor system health via HTTP endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single check
  cab-health-monitor --oneshot

  # Continuous monitoring
  cab-health-monitor --watch

  # Custom endpoint
  cab-health-monitor --url http://localhost:9000/health --watch

  # Verbose output with short interval
  cab-health-monitor --watch --verbose --interval 2
        """,
    )

    # Connection
    parser.add_argument(
        "--url",
        default=os.getenv("HEALTH_URL", "http://127.0.0.1:8000/health"),
        help="Health endpoint URL",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("HEALTH_TIMEOUT_SEC", "30")),
        help="Request timeout in seconds",
    )

    # Mode
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--oneshot",
        action="store_true",
        help="Single check and exit with status code",
    )

    mode_group.add_argument(
        "--watch",
        action="store_true",
        help="Continuously monitor health",
    )

    # Watch options
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("HEALTH_CHECK_INTERVAL", "5")),
        help="Check interval in seconds (watch mode)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output (full JSON)",
    )

    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear/redraw screen between checks",
    )

    # Alerts
    parser.add_argument(
        "--alert-webhook",
        help="Webhook URL for alerts on status change",
    )

    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    # Optional notifier
    notifier: Optional[HealthAlertNotifier] = None
    if args.alert_webhook:
        notifier = HealthAlertNotifier(args.alert_webhook)

    # Create monitor
    monitor = HealthMonitor(
        url=args.url,
        timeout=args.timeout,
        interval=args.interval,
        verbose=args.verbose,
        notifier=notifier,
        clear_screen=not args.no_clear,
    )

    # Run appropriate mode
    if args.oneshot:
        return await monitor.check_once()

    if args.watch:
        try:
            await monitor.watch()
            return 0
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user")
            print(f"📊 Final stats: {monitor._format_stats()}")
            return 0

    # Default to oneshot
    return await monitor.check_once()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    try:
        exit_code = asyncio.run(async_main(args))
        sys.exit(exit_code)

    except KeyboardInterrupt:
        sys.exit(0)

    except Exception as e:
        _log.error("health_monitor_error", exc_info=True)
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
