from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple, Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms


@dataclass
class RiskConfig:
    max_position_base: Decimal = dec("0")          # 0 => выключено
    max_loss_day_quote: Decimal = dec("0")         # 0 => выключено
    cooldown_after_loss_min: int = 0               # минуты, 0 => выключено
    stop_on_slippage_pct: Decimal = dec("0")       # зарезервировано (0 => выключено)

    @classmethod
    def from_settings(cls, s: Any) -> "RiskConfig":
        def _d(name: str, default: str = "0") -> Decimal:
            v = getattr(s, name, default)
            return dec(str(v if v is not None else default))
        def _i(name: str, default: int = 0) -> int:
            try:
                return int(getattr(s, name, default) or default)
            except Exception:
                return default

        return cls(
            max_position_base=_d("MAX_POSITION_BASE", "0"),
            max_loss_day_quote=_d("MAX_LOSS_DAY_QUOTE", "0"),
            cooldown_after_loss_min=_i("COOLDOWN_AFTER_LOSS_MIN", 0),
            stop_on_slippage_pct=_d("STOP_ON_SLIPPAGE_PCT", "0"),
        )


class RiskManager:
    """
    Минимальный, но практичный RiskGate для long-only:
    - Ограничение позиции по базе (MAX_POSITION_BASE)
    - Дневной стоп по убытку в котировке (MAX_LOSS_DAY_QUOTE) + cooldown
    - Защита от «перепродажи» (sell не больше доступного base)
    """
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._storage = None
        self._cooldown_until_ms: int = 0

    # подключаем Storage отдельно, чтобы не ломать существующие вызовы
    def attach_storage(self, storage) -> None:
        self._storage = storage

    # публичная проверка
    def allow(
        self,
        *,
        symbol: str,
        action: str,
        quote_amount: Optional[Decimal],
        base_amount: Optional[Decimal],
    ) -> Tuple[bool, str]:
        action = (action or "").lower().strip()
        if action in ("", "hold", "none"):
            return True, "hold"

        # 0) cooldown
        if self._cooldown_until_ms and now_ms() < self._cooldown_until_ms:
            return False, "cooldown_after_loss"

        # 1) дневной стоп по убытку
        if self.cfg.max_loss_day_quote > 0 and self._storage is not None:
            try:
                pnl = self._storage.trades.daily_pnl_quote(symbol)
                if pnl <= (dec("0") - self.cfg.max_loss_day_quote):
                    # уходим в cooldown (если задан)
                    if self.cfg.cooldown_after_loss_min > 0:
                        self._cooldown_until_ms = now_ms() + self.cfg.cooldown_after_loss_min * 60_000
                    return False, f"day_loss_exceeded:{pnl}"
            except Exception:
                # при сбое в расчёте PNЛ — не блокируем, но и не снимаем защит
                pass

        # 2) ограничение позиции по базе
        if self.cfg.max_position_base > 0 and self._storage is not None:
            try:
                pos = self._storage.positions.get_position(symbol)
                cur_base = dec(str(pos.base_qty or 0))
                # для buy не знаем точный base до тикера — используем консервативное правило:
                # если уже достигли/превысили лимит — новые buy блокируем
                if action == "buy" and cur_base >= self.cfg.max_position_base:
                    return False, "max_position_reached"
                # для sell — не даём продать больше текущего base
                if action == "sell":
                    want_base = dec(str(base_amount or 0))
                    if want_base > cur_base:
                        return False, "insufficient_base_for_sell"
            except Exception:
                # на ошибках в сторедже — не блокируем
                pass

        # 3) (зарезервировано) стоп на проскальзывании
        # Реализуется в местах, где известна котировка/филл. Оставляем флаг в конфиге.

        return True, "ok"
