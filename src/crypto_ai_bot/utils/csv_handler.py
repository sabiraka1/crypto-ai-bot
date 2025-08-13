# src/crypto_ai_bot/core/state_manager.py
"""
🧠 StateManager — простое и надёжное хранилище состояния
- in_position/opening, атрибуты позиции
- дневной дроудаун и эквити
- кулдаун после закрытия (или ошибки)
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from crypto_ai_bot.config.settings import Settings


@dataclass
class _InternalState:
    # позиция
    in_position: bool = False
    opening: bool = False
    symbol: Optional[str] = None
    entry_price: Optional[float] = None
    qty_base: Optional[float] = None
    qty_usd: Optional[float] = None
    sl_atr: Optional[float] = None
    tp1_atr: Optional[float] = None
    tp2_atr: Optional[float] = None
    partial_taken: bool = False
    trailing_on: bool = False
    entry_ts: Optional[str] = None
    buy_score: Optional[float] = None
    ai_score: Optional[float] = None
    order_id: Optional[str] = None
    last_manage_check: Optional[str] = None

    # счёт
    equity: float = 1000.0
    day_start_equity: float = 1000.0
    day_high_equity: float = 1000.0

    # сервисные флаги
    cooldown_until_ts: float = 0.0


class StateManager:
    """Потокобезопасный state-хранилище с удобными аксессорами."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.cfg = settings or Settings()
        self._lock = threading.RLock()
        eq0 = float(getattr(self.cfg, "EQUITY_START", 1000.0))
        self._state = _InternalState(equity=eq0, day_start_equity=eq0, day_high_equity=eq0)

    # ------ базовые get/set --------------------------------------------------
    @property
    def state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state.__dict__)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return getattr(self._state, key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            setattr(self._state, key, value)

    # ------ позиция ----------------------------------------------------------
    def reset_position(self) -> None:
        with self._lock:
            self._state.in_position = False
            self._state.opening = False
            self._state.symbol = None
            self._state.entry_price = None
            self._state.qty_base = None
            self._state.qty_usd = None
            self._state.sl_atr = None
            self._state.tp1_atr = None
            self._state.tp2_atr = None
            self._state.partial_taken = False
            self._state.trailing_on = False
            self._state.entry_ts = None
            self._state.buy_score = None
            self._state.ai_score = None
            self._state.order_id = None
            self._state.last_manage_check = None

    def get_open_positions_count(self) -> int:
        with self._lock:
            return 1 if (self._state.in_position or self._state.opening) else 0

    # ------ счёт / дроудаун --------------------------------------------------
    def set_equity(self, equity: float) -> None:
        with self._lock:
            self._state.equity = float(equity)
            # обновляем дневной максимум
            if self._state.equity > self._state.day_high_equity:
                self._state.day_high_equity = self._state.equity

    def apply_trade_pnl(self, pnl_abs: float) -> None:
        """Обновляет эквити после сделки (+/- pnl_abs)."""
        with self._lock:
            new_eq = (self._state.equity or 0.0) + float(pnl_abs or 0.0)
            self._state.equity = new_eq
            if new_eq > self._state.day_high_equity:
                self._state.day_high_equity = new_eq

    def reset_daily_counters(self, equity: Optional[float] = None) -> None:
        """Сбрасывает дневную статистику (вызывай 1 раз в сутки по cron/scheduler)."""
        with self._lock:
            eq = float(equity) if equity is not None else float(self._state.equity or 0.0)
            self._state.day_start_equity = eq
            self._state.day_high_equity = eq

    def get_daily_drawdown(self) -> float:
        """Текущий дневной дроудаун (0..1)."""
        with self._lock:
            peak = max(self._state.day_high_equity, self._state.day_start_equity, 1e-9)
            cur = self._state.equity or 0.0
            dd = (peak - cur) / peak
            return max(0.0, float(dd))

    # ------ кулдаун ----------------------------------------------------------
    def start_cooldown(self, minutes: Optional[int] = None) -> None:
        mins = minutes if minutes is not None else int(getattr(self.cfg, "COOLDOWN_AFTER_LOSS_MIN", 15))
        until = time.time() + mins * 60
        with self._lock:
            self._state.cooldown_until_ts = until

    def in_cooldown(self) -> bool:
        with self._lock:
            return time.time() < float(self._state.cooldown_until_ts or 0.0)
