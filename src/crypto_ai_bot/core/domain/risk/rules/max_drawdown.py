from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_ai_bot.utils.decimal import dec


@dataclass
class MaxDrawdownRule:
    """Правило ограничения просадки."""

    max_drawdown_pct: Decimal = dec("10.0")  # 10%
    max_daily_loss_quote: Decimal = dec("100")

    def check(self,
             current_balance: Decimal,
             peak_balance: Decimal,
             daily_pnl: Decimal) -> tuple[bool, str]:
        """
        Проверяет текущую просадку.
        Returns: (allowed, reason)
        """
        # Проверка дневного лимита убытков
        if daily_pnl < -abs(self.max_daily_loss_quote):
            return False, f"daily_loss_exceeded_{daily_pnl}"

        # Проверка общей просадки от пика
        if peak_balance > 0:
            drawdown_pct = ((peak_balance - current_balance) / peak_balance) * dec("100")
            if drawdown_pct > self.max_drawdown_pct:
                return False, f"max_drawdown_{drawdown_pct:.2f}%"

        return True, "ok"

    def calculate_drawdown(self, balances: list[Decimal]) -> dict[str, Decimal]:
        """
        Рассчитывает метрики просадки для серии балансов.
        Returns: {"current": x, "max": y, "peak": z}
        """
        if not balances:
            return {"current": dec("0"), "max": dec("0"), "peak": dec("0")}

        peak = balances[0]
        max_dd = dec("0")
        current_dd = dec("0")

        for balance in balances:
            if balance > peak:
                peak = balance

            if peak > 0:
                dd = ((peak - balance) / peak) * dec("100")
                max_dd = max(max_dd, dd)
                current_dd = dd

        return {
            "current": current_dd,
            "max": max_dd,
            "peak": peak
        }

    def recovery_ratio(self, current: Decimal, trough: Decimal, peak: Decimal) -> Decimal:
        """Процент восстановления от минимума к пику."""
        if peak <= trough:
            return dec("100")

        recovery = ((current - trough) / (peak - trough)) * dec("100")
        return max(dec("0"), min(dec("100"), recovery))
