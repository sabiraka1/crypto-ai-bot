from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, List, Mapping, Optional, Union

from crypto_ai_bot.utils.decimal import dec


# -----------------------
# Конфигурация риска
# -----------------------
@dataclass
class RiskConfig:
    # базовые лимиты
    cooldown_sec: int = 60
    max_spread_pct: Decimal = dec("0.0")
    max_position_base: Decimal = dec("0.0")
    max_orders_per_hour: int = 0
    daily_loss_limit_quote: Decimal = dec("0.0")
    # доп. лимиты (оценочные)
    max_fee_pct: Decimal = dec("0.0")
    max_slippage_pct: Decimal = dec("0.0")
    # совместимость со старыми полями в приложении
    max_orders_5m: int = 0
    max_turnover_day: Decimal = dec("0.0")

    @classmethod
    def from_settings(cls, s: Any) -> "RiskConfig":
        """
        Сборка конфига из Settings. Поля названы в соответствии с текущим Settings.
        Доп. поля max_orders_5m/max_turnover_day подтягиваются, если заданы.
        """
        return cls(
            cooldown_sec=int(getattr(s, "RISK_COOLDOWN_SEC", 60) or 60),
            max_spread_pct=dec(str(getattr(s, "RISK_MAX_SPREAD_PCT", 0) or 0)),
            max_position_base=dec(str(getattr(s, "RISK_MAX_POSITION_BASE", 0) or 0)),
            max_orders_per_hour=int(getattr(s, "RISK_MAX_ORDERS_PER_HOUR", 0) or 0),
            daily_loss_limit_quote=dec(str(getattr(s, "RISK_DAILY_LOSS_LIMIT_QUOTE", 0) or 0)),
            max_fee_pct=dec(str(getattr(s, "RISK_MAX_FEE_PCT", 0) or 0)),
            max_slippage_pct=dec(str(getattr(s, "RISK_MAX_SLIPPAGE_PCT", 0) or 0)),
            # backward-compat (если присутствуют в окружении)
            max_orders_5m=int(getattr(s, "RISK_MAX_ORDERS_5M", 0) or 0),
            max_turnover_day=dec(str(getattr(s, "SAFETY_MAX_TURNOVER_QUOTE_PER_DAY", 0) or 0)),
        )


# -----------------------
# Входные факторы риска
# -----------------------
@dataclass
class RiskInputs:
    spread_pct: Decimal = dec("0")
    position_base: Decimal = dec("0")
    recent_orders: int = 0          # за последний «окно» (например, час)
    pnl_daily_quote: Decimal = dec("0")
    cooldown_active: bool = False
    est_fee_pct: Decimal = dec("0")
    est_slippage_pct: Decimal = dec("0")


# -----------------------
# RiskManager (чистый)
# -----------------------
@dataclass
class RiskManager:
    config: RiskConfig

    def _normalize(self, value: Union[RiskInputs, Mapping[str, Any]]) -> RiskInputs:
        if isinstance(value, RiskInputs):
            return value
        # поддержка старого интерфейса через dict
        return RiskInputs(
            spread_pct=dec(str(value.get("spread_pct", 0))),
            position_base=dec(str(value.get("position_base", 0))),
            recent_orders=int(value.get("recent_orders", 0) or 0),
            pnl_daily_quote=dec(str(value.get("pnl_daily_quote", 0))),
            cooldown_active=bool(value.get("cooldown_active", False)),
            est_fee_pct=dec(str(value.get("est_fee_pct", 0))),
            est_slippage_pct=dec(str(value.get("est_slippage_pct", 0))),
        )

    def check(self, inputs: Union[RiskInputs, Mapping[str, Any]]) -> Mapping[str, Any]:
        """
        Унифицированная проверка риска. Возвращает:
        {"ok": bool, "reasons": [..], "limits": {...}}
        """
        cfg = self.config
        x = self._normalize(inputs)

        reasons: List[str] = []

        # 1) cooldown
        if x.cooldown_active and cfg.cooldown_sec > 0:
            reasons.append("cooldown_active")

        # 2) спред
        if cfg.max_spread_pct > 0 and x.spread_pct > cfg.max_spread_pct:
            reasons.append("spread_too_wide")

        # 3) позиция
        if cfg.max_position_base > 0 and x.position_base > cfg.max_position_base:
            reasons.append("position_limit_exceeded")

        # 4) частота/скорость ордеров (за час)
        if cfg.max_orders_per_hour > 0 and x.recent_orders > cfg.max_orders_per_hour:
            reasons.append("orders_rate_limit")

        # 5) дневной лимит по убытку (значение отрицательное — убыток)
        if cfg.daily_loss_limit_quote > 0 and x.pnl_daily_quote < (dec("0") - cfg.daily_loss_limit_quote):
            reasons.append("daily_loss_limit_reached")

        # 6) оценка издержек
        if cfg.max_fee_pct > 0 and x.est_fee_pct > cfg.max_fee_pct:
            reasons.append("fee_limit_exceeded")
        if cfg.max_slippage_pct > 0 and x.est_slippage_pct > cfg.max_slippage_pct:
            reasons.append("slippage_limit_exceeded")

        return {
            "ok": len(reasons) == 0,
            "reasons": reasons,
            "limits": {
                "cooldown_sec": cfg.cooldown_sec,
                "max_spread_pct": str(cfg.max_spread_pct),
                "max_position_base": str(cfg.max_position_base),
                "max_orders_per_hour": cfg.max_orders_per_hour,
                "daily_loss_limit_quote": str(cfg.daily_loss_limit_quote),
                "max_fee_pct": str(cfg.max_fee_pct),
                "max_slippage_pct": str(cfg.max_slippage_pct),
                # совместимость
                "max_orders_5m": cfg.max_orders_5m,
                "max_turnover_day": str(cfg.m
