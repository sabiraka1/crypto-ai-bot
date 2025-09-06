"""Performance reporting CLI utility.

Located in cli layer - generates PnL reports and trading statistics.
Supports daily, weekly, monthly reports with detailed analytics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from crypto_ai_bot.app.compose import compose
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.symbols import canonical

_log = get_logger(__name__)


# ============== Report Types ==============

class ReportPeriod(Enum):
    """Report period types."""

    TODAY = "today"
    YESTERDAY = "yesterday"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    CUSTOM = "custom"

    def get_date_range(self) -> tuple[datetime, datetime]:
        """Get [start, end] for period in UTC. End is 'now' except YESTERDAY."""
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self == self.TODAY:
            return today, now

        if self == self.YESTERDAY:
            y0 = today - timedelta(days=1)
            y1 = today - timedelta(microseconds=1)
            return y0, y1

        if self == self.WEEK:
            start = today - timedelta(days=7)
            return start, now

        if self == self.MONTH:
            start = today - timedelta(days=30)
            return start, now

        if self == self.YEAR:
            start = today - timedelta(days=365)
            return start, now

        raise ValueError("Custom period requires explicit dates")


class ReportFormat(Enum):
    """Output format types."""

    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    MARKDOWN = "markdown"


# ============== Data Classes ==============

class PerformanceMetrics:
    """Trading performance metrics (Decimal-backed numbers as strings for safety)."""

    def __init__(self) -> None:
        self.realized_pnl = dec("0")
        self.unrealized_pnl = dec("0")
        self.total_pnl = dec("0")
        self.turnover = dec("0")
        self.trades_count = 0
        self.wins = 0
        self.losses = 0
        self.win_rate = 0.0
        self.avg_win = dec("0")
        self.avg_loss = dec("0")
        self.profit_factor = 0.0
        self.sharpe_ratio = 0.0  # not computed here (needs timeseries of returns)
        self.max_drawdown = dec("0")  # not computed here (needs equity curve)
        self.fees_paid = dec("0")

    def calculate_derived(self) -> None:
        """Calculate derived metrics."""
        total_trades = self.trades_count
        if total_trades > 0:
            self.win_rate = (self.wins / total_trades) * 100.0
        self.total_pnl = self.realized_pnl + self.unrealized_pnl

        # Profit factor (Σwins / Σlosses)
        total_wins = self.avg_win * self.wins if self.wins > 0 else dec("0")
        total_losses = self.avg_loss * self.losses if self.losses > 0 else dec("0")
        if total_losses > 0:
            try:
                self.profit_factor = float(total_wins / total_losses)
            except Exception:
                self.profit_factor = 0.0
        else:
            # if no losses, define PF as 'infinite' → clamp to a large number
            self.profit_factor = float("inf") if total_wins > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to plain dict for JSON/CSV writers."""
        return {
            "realized_pnl": float(self.realized_pnl),
            "unrealized_pnl": float(self.unrealized_pnl),
            "total_pnl": float(self.total_pnl),
            "turnover": float(self.turnover),
            "trades_count": self.trades_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "avg_win": float(self.avg_win),
            "avg_loss": float(self.avg_loss),
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": float(self.max_drawdown),
            "fees_paid": float(self.fees_paid),
        }


# ============== Report Generator ==============

class PerformanceReporter:
    """Generate performance reports."""

    def __init__(self, container: Any):
        self.container = container
        self.storage = container.storage
        self.broker = container.broker
        self.settings = container.settings

    def _get_symbols(self) -> list[str]:
        """Get trading symbols from settings."""
        raw = (getattr(self.settings, "SYMBOLS", "") or "").strip()
        if raw:
            return [canonical(s.strip()) for s in raw.split(",") if s.strip()]

        if hasattr(self.settings, "SYMBOL"):
            return [canonical(getattr(self.settings, "SYMBOL"))]

        return ["BTC/USDT"]

    async def generate_report(
        self,
        period: ReportPeriod,
        symbols: Optional[list[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict[str, PerformanceMetrics]:
        """Generate performance report for period."""
        # Determine date range
        if period == ReportPeriod.CUSTOM:
            if not start_date or not end_date:
                raise ValueError("Custom period requires start and end dates")
        else:
            start_date, end_date = period.get_date_range()

        assert start_date is not None and end_date is not None

        # Get symbols
        if not symbols:
            symbols = self._get_symbols()

        # Generate metrics for each symbol
        results: dict[str, PerformanceMetrics] = {}

        for symbol in symbols:
            metrics = await self._calculate_metrics(symbol, start_date, end_date)
            results[symbol] = metrics

        # Add total row
        results["TOTAL"] = self._calculate_totals(results)

        return results

    async def _calculate_metrics(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> PerformanceMetrics:
        """Calculate metrics for single symbol."""
        metrics = PerformanceMetrics()

        try:
            # Trades for inclusive date range (storage typically expects date objects)
            trades_repo = getattr(self.storage, "trades", None)
            trades = []
            if trades_repo and hasattr(trades_repo, "get_by_date_range"):
                # end_date inclusive (clip to date end)
                trades = trades_repo.get_by_date_range(
                    symbol=symbol,
                    start_date=start_date.date(),
                    end_date=end_date.date(),
                )

            # Realized PnL + wins/losses/fees + turnover
            for t in trades:
                pnl = dec(str(t.get("pnl", 0) or 0))
                metrics.realized_pnl += pnl
                if pnl > 0:
                    metrics.wins += 1
                elif pnl < 0:
                    metrics.losses += 1

                fee = dec(str(t.get("fee", 0) or 0))
                metrics.fees_paid += fee

                amount = dec(str(t.get("amount", 0) or 0))
                price = dec(str(t.get("price", 0) or 0))
                metrics.turnover += amount * price

            metrics.trades_count = len(trades)

            # Unrealized PnL from broker position (object or dict)
            if hasattr(self.broker, "fetch_position"):
                try:
                    position = await self.broker.fetch_position(symbol)
                except Exception:
                    position = None

                if position:
                    def _get(obj: Any, name: str, default: str = "0") -> Any:
                        if hasattr(obj, name):
                            try:
                                return getattr(obj, name)
                            except Exception:
                                return default
                        if isinstance(obj, dict):
                            return obj.get(name, default)
                        return default

                    entry_price = dec(str(_get(position, "entry_price", "0")))
                    current_price = dec(str(_get(position, "current_price", "0")))
                    amount = dec(str(_get(position, "amount", "0")))

                    if amount != dec("0") and entry_price > dec("0") and current_price > dec("0"):
                        # long if amount>0, short if amount<0 -> sign respected
                        metrics.unrealized_pnl = (current_price - entry_price) * amount

            # Average win/loss
            if metrics.wins > 0:
                wins_sum = sum(dec(str(t.get("pnl", 0) or 0)) for t in trades if (t.get("pnl", 0) or 0) > 0)
                metrics.avg_win = wins_sum / metrics.wins

            if metrics.losses > 0:
                losses_sum = sum(abs(dec(str(t.get("pnl", 0) or 0))) for t in trades if (t.get("pnl", 0) or 0) < 0)
                metrics.avg_loss = losses_sum / metrics.losses

            # Derived metrics (win rate, total pnl, profit factor, etc.)
            metrics.calculate_derived()

        except Exception as e:
            _log.error(
                "metrics_calculation_failed",
                exc_info=True,
                extra={"symbol": symbol, "error": str(e)},
            )

        return metrics

    def _calculate_totals(self, results: dict[str, PerformanceMetrics]) -> PerformanceMetrics:
        """Calculate totals across symbols (TOTAL key excluded if present)."""
        total = PerformanceMetrics()

        for key, m in results.items():
            if key == "TOTAL":
                continue
            total.realized_pnl += m.realized_pnl
            total.unrealized_pnl += m.unrealized_pnl
            total.turnover += m.turnover
            total.trades_count += m.trades_count
            total.wins += m.wins
            total.losses += m.losses
            total.fees_paid += m.fees_paid

        # Derived (win rate / total pnl / profit factor)
        # avg_win/avg_loss here are not strictly meaningful without raw trade list;
        # we keep them zeroed to avoid misleading numbers.
        total.calculate_derived()
        return total


# ============== Output Formatters ==============

class ReportFormatter:
    """Format reports for output."""

    @staticmethod
    def format_table(results: dict[str, PerformanceMetrics]) -> str:
        """Format as ASCII table with fixed widths."""
        lines: list[str] = []

        headers = [
            "Symbol",
            "Realized PnL",
            "Unrealized PnL",
            "Total PnL",
            "Turnover",
            "Trades",
            "Win Rate",
            "Fees",
        ]
        widths = [15, 16, 16, 16, 16, 8, 10, 12]

        header_row = "".join(h.ljust(w) for h, w in zip(headers, widths))
        lines.append(header_row)
        lines.append("-" * sum(widths))

        # Stable order: symbols (except TOTAL), then TOTAL
        symbols = [k for k in results.keys() if k != "TOTAL"]
        for symbol in symbols:
            m = results[symbol]
            row = (
                symbol.ljust(widths[0])
                + f"{m.realized_pnl:+.2f}".ljust(widths[1])
                + f"{m.unrealized_pnl:+.2f}".ljust(widths[2])
                + f"{m.total_pnl:+.2f}".ljust(widths[3])
                + f"{m.turnover:.2f}".ljust(widths[4])
                + f"{m.trades_count}".ljust(widths[5])
                + f"{m.win_rate:.1f}%".ljust(widths[6])
                + f"{m.fees_paid:.2f}".ljust(widths[7])
            )
            lines.append(row)

        if "TOTAL" in results:
            lines.append("-" * sum(widths))
            m = results["TOTAL"]
            row = (
                "TOTAL".ljust(widths[0])
                + f"{m.realized_pnl:+.2f}".ljust(widths[1])
                + f"{m.unrealized_pnl:+.2f}".ljust(widths[2])
                + f"{m.total_pnl:+.2f}".ljust(widths[3])
                + f"{m.turnover:.2f}".ljust(widths[4])
                + f"{m.trades_count}".ljust(widths[5])
                + f"{m.win_rate:.1f}%".ljust(widths[6])
                + f"{m.fees_paid:.2f}".ljust(widths[7])
            )
            lines.append(row)

        return "\n".join(lines)

    @staticmethod
    def format_json(results: dict[str, PerformanceMetrics]) -> str:
        """Format as JSON (all symbols including TOTAL)."""
        data = {symbol: m.to_dict() for symbol, m in results.items()}
        return json.dumps(data, indent=2)

    @staticmethod
    def format_csv(results: dict[str, PerformanceMetrics]) -> str:
        """Format as CSV."""
        headers = [
            "Symbol",
            "Realized_PnL",
            "Unrealized_PnL",
            "Total_PnL",
            "Turnover",
            "Trades",
            "Wins",
            "Losses",
            "Win_Rate",
            "Avg_Win",
            "Avg_Loss",
            "Profit_Factor",
            "Fees",
        ]
        lines = [",".join(headers)]

        for symbol, m in results.items():
            row = [
                symbol,
                f"{m.realized_pnl:.2f}",
                f"{m.unrealized_pnl:.2f}",
                f"{m.total_pnl:.2f}",
                f"{m.turnover:.2f}",
                str(m.trades_count),
                str(m.wins),
                str(m.losses),
                f"{m.win_rate:.2f}",
                f"{m.avg_win:.2f}",
                f"{m.avg_loss:.2f}",
                ("inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"),
                f"{m.fees_paid:.2f}",
            ]
            lines.append(",".join(row))

        return "\n".join(lines)

    @staticmethod
    def format_markdown(results: dict[str, PerformanceMetrics]) -> str:
        """Format as Markdown (summary + detail)."""
        lines: list[str] = []
        lines.append("# Performance Report")
        lines.append("")

        if "TOTAL" in results:
            t = results["TOTAL"]
            lines.append("## Summary")
            lines.append("")
            lines.append(f"- **Total PnL**: {t.total_pnl:+.2f} USDT")
            lines.append(f"- **Win Rate**: {t.win_rate:.1f}%")
            lines.append(f"- **Total Trades**: {t.trades_count}")
            lines.append(f"- **Turnover**: {t.turnover:.2f} USDT")
            lines.append("")

        lines.append("## Detailed Performance")
        lines.append("")
        lines.append("| Symbol | Realized PnL | Unrealized PnL | Total PnL | Trades | Win Rate | Fees |")
        lines.append("|--------|---------------|----------------|-----------|--------|----------|------|")

        symbols = [k for k in results.keys() if k != "TOTAL"]
        for symbol in symbols:
            m = results[symbol]
            lines.append(
                f"| {symbol} | {m.realized_pnl:+.2f} | {m.unrealized_pnl:+.2f} | "
                f"{m.total_pnl:+.2f} | {m.trades_count} | {m.win_rate:.1f}% | {m.fees_paid:.2f} |"
            )

        if "TOTAL" in results:
            m = results["TOTAL"]
            lines.append(
                f"| **TOTAL** | **{m.realized_pnl:+.2f}** | **{m.unrealized_pnl:+.2f}** | "
                f"**{m.total_pnl:+.2f}** | **{m.trades_count}** | **{m.win_rate:.1f}%** | **{m.fees_paid:.2f}** |"
            )

        return "\n".join(lines)


# ============== CLI Entry Point ==============

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="cab-perf",
        description="Trading performance reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Today's performance
  cab-perf

  # Yesterday's report
  cab-perf --period yesterday

  # Weekly report in JSON
  cab-perf --period week --format json

  # Custom date range
  cab-perf --custom --start 2024-01-01 --end 2024-01-31

  # Specific symbols
  cab-perf --symbols BTC/USDT,ETH/USDT
        """,
    )

    # Period selection
    period_group = parser.add_mutually_exclusive_group()
    period_group.add_argument(
        "--period",
        type=str,
        choices=["today", "yesterday", "week", "month", "year"],
        default="today",
        help="Report period",
    )
    period_group.add_argument(
        "--custom",
        action="store_true",
        help="Use custom date range (requires --start and --end)",
    )

    # Custom date range
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")

    # Symbols
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols")

    # Output format
    parser.add_argument(
        "--format",
        type=str,
        choices=["table", "json", "csv", "markdown"],
        default="table",
        help="Output format",
    )

    # Additional options
    parser.add_argument("--output", type=str, help="Output file (default: stdout)")

    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    container = None
    try:
        # Create container
        container = await compose()

        # Create reporter
        reporter = PerformanceReporter(container)

        # Parse period
        if args.custom:
            if not args.start or not args.end:
                print("Error: Custom period requires --start and --end dates", file=sys.stderr)
                return 1
            try:
                start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                # inclusive end of day
                end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            except ValueError:
                print("Error: Invalid date format, expected YYYY-MM-DD", file=sys.stderr)
                return 1
            period = ReportPeriod.CUSTOM
        else:
            period = ReportPeriod(args.period)
            start_date = None
            end_date = None

        # Parse symbols
        symbols: Optional[list[str]] = None
        if args.symbols:
            symbols = [canonical(s.strip()) for s in args.symbols.split(",") if s.strip()]

        # Generate report
        results = await reporter.generate_report(
            period=period,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

        # Format output
        fmt = ReportFormat(args.format)
        if fmt == ReportFormat.TABLE:
            output = ReportFormatter.format_table(results)
        elif fmt == ReportFormat.JSON:
            output = ReportFormatter.format_json(results)
        elif fmt == ReportFormat.CSV:
            output = ReportFormatter.format_csv(results)
        else:
            output = ReportFormatter.format_markdown(results)

        # Write output
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Report saved to: {args.output}")
        else:
            print(output)

        return 0

    except Exception as e:
        _log.error("performance_report_error", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        return 1

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
