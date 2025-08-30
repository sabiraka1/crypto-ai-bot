from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple, Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms


@dataclass
class RiskConfig:
    max_position_base: Decimal = dec("0")
    max_loss_day_quote: Decimal = dec("0")
    cooldown_after_loss_min: int = 0
    stop_on_slippage_pct: Decimal = dec("0")

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
    RiskGate long-only с пер-символьными оверрайдами, читаемыми на лету:
    - Пер-символьные ключи имеют вид NAME_<BASE>_<QUOTE> (например MAX_POSITION_BASE_BTC_USDT).
    - Если пер-символьного нет — используем глобальный из cfg.
    """
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._storage = None
        self._settings = None
        self._cooldown_until_ms: int = 0

    def attach_storage(self, storage) -> None:
        self._storage = storage

    def attach_settings(self, settings) -> None:
        self._settings = settings

    # --- helpers ---
    def _per_symbol_decimal(self, symbol: str, name: str, fallback: Decimal) -> Decimal:
        if not self._settings:
            return fallback
        try:
            base, quote = str(symbol).replace("-", "/").split("/")
            key = f"{name}_{base}_{quote}".upper().replace("/", "_")
            v = getattr(self._settings, key, None)
            return dec(str(v)) if v not in (None, "") else fallback
        except Exception:
            return fallback

    def _per_symbol_int(self, symbol: str, name: str, fallback: int) -> int:
        if not self._settings:
            return fallback
        try:
            base, quote = str(symbol).replace("-", "/").split("/")
            key = f"{name}_{base}_{quote}".upper().replace("/", "_")
            v = getattr(self._settings, key, None)
            return int(v) if v not in (None, "") else fallback
        except Exception:
            return fallback

    # --- policy ---
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

        # cooldown
        if self._cooldown_until_ms and now_ms() < self._cooldown_until_ms:
            return False, "cooldown_after_loss"

        # дневной стоп по убытку (пер-символьный override)
        mldq = self._per_symbol_decimal(symbol, "MAX_LOSS_DAY_QUOTE", self.cfg.max_loss_day_quote)
        if mldq > 0 and self._storage is not None:
            try:
                pnl = self._storage.trades.daily_pnl_quote(symbol)
                if pnl <= (dec("0") - mldq):
                    cd = self._per_symbol_int(symbol, "COOLDOWN_AFTER_LOSS_MIN", self.cfg.cooldown_after_loss_min)
                    if cd > 0:
                        self._cooldown_until_ms = now_ms() + cd * 60_000
                    return False, f"day_loss_exceeded:{pnl}"
            except Exception:
                pass

        # ограничение позиции
        mpb = self._per_symbol_decimal(symbol, "MAX_POSITION_BASE", self.cfg.max_position_base)
        if mpb > 0 and self._storage is not None:
            try:
                pos = self._storage.positions.get_position(symbol)
                cur_base = dec(str(pos.base_qty or 0))
                if action == "buy" and cur_base >= mpb:
                    return False, "max_position_reached"
                if action == "sell":
                    want_base = dec(str(base_amount or 0))
                    if want_base > cur_base:
                        return False, "insufficient_base_for_sell"
            except Exception:
                pass

        # проскальзывание — реализуется в местах знания фактической цены; флаг оставляем для будущего
        return True, "ok"
