from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from crypto_ai_bot.utils.decimal import dec
from .base import BaseStrategy, Decision, MarketData, StrategyContext

# Стратегии (ниже импортируются по именам)
from .ema_atr import EmaAtrConfig, EmaAtrStrategy
from .ema_cross import EmaCrossStrategy
from .rsi_momentum import RSIMomentumStrategy
from .bollinger_bands import BollingerBandsStrategy
from .donchian_breakout import DonchianBreakoutStrategy
from .supertrend import SupertrendStrategy
from .stochastic_adx import StochasticADXStrategy
from .keltner_squeeze import KeltnerSqueezeStrategy
from .vwap_reversion import VWAPReversionStrategy


Signal = Decision


@dataclass
class _Weighting:
    mode: str = "first"  # first | vote | weighted
    min_confidence: Decimal = dec("0.0")
    weights: Dict[str, Decimal] = None  # name -> weight


def _parse_strategy_list(raw: str | None) -> List[str]:
    if not raw:
        return ["ema_atr"]
    return [x.strip().lower() for x in str(raw).split(",") if x.strip()]


def _parse_weights(raw: str | None) -> Dict[str, Decimal]:
    """
    Формат: "ema_atr:1.0, donchian_breakout:1.5"
    """
    out: Dict[str, Decimal] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, w = part.split(":", 1)
        name = name.strip().lower()
        try:
            out[name] = dec(str(float(w.strip())))
        except Exception:
            continue
    return out


class StrategyManager:
    """
    Подгружает и агрегирует стратегии.
    Совместим с прежним API: StrategyManager(md, settings).decide(symbol) -> Decision
    """

    def __init__(self, *, md: MarketData, settings: Any) -> None:
        self._md = md
        self._settings = settings
        self._strategies: List[tuple[str, BaseStrategy]] = []
        self._wcfg = self._build_weighting()
        self._load_strategies()

    def _build_weighting(self) -> _Weighting:
        mode = str(getattr(self._settings, "STRATEGY_MODE", "first") or "first").lower()
        min_conf = dec(str(getattr(self._settings, "STRATEGY_MIN_CONFIDENCE", "0.0") or "0.0"))
        raw_weights = getattr(self._settings, "STRATEGY_WEIGHTS", None)
        weights = _parse_weights(raw_weights)
        return _Weighting(mode=mode, min_confidence=min_conf, weights=weights)

    def _add(self, name: str) -> None:
        """
        Регистрирует стратегию по имени. Параметры берутся из settings при наличии.
        """
        n = name.lower()
        if n == "ema_atr":
            cfg = EmaAtrConfig(
                ema_short=int(getattr(self._settings, "EMA_SHORT", 12) or 12),
                ema_long=int(getattr(self._settings, "EMA_LONG", 26) or 26),
                atr_period=int(getattr(self._settings, "ATR_PERIOD", 14) or 14),
                atr_max_pct=dec(str(getattr(self._settings, "ATR_MAX_PCT", "1000") or "1000")),
                ema_min_slope=dec(str(getattr(self._settings, "EMA_MIN_SLOPE", "0") or "0")),
            )
            self._strategies.append((n, EmaAtrStrategy(cfg)))
        elif n == "ema_cross":
            self._strategies.append((n, EmaCrossStrategy()))
        elif n == "rsi_momentum":
            self._strategies.append((n, RSIMomentumStrategy()))
        elif n == "bollinger":
            self._strategies.append((n, BollingerBandsStrategy()))
        elif n == "donchian_breakout":
            self._strategies.append((n, DonchianBreakoutStrategy()))
        elif n == "supertrend":
            self._strategies.append((n, SupertrendStrategy()))
        elif n == "stochastic_adx":
            self._strategies.append((n, StochasticADXStrategy()))
        elif n == "keltner_squeeze":
            self._strategies.append((n, KeltnerSqueezeStrategy()))
        elif n == "vwap_reversion":
            self._strategies.append((n, VWAPReversionStrategy()))
        # неизвестные имена — молча игнорируем (совместимость)

    def _load_strategies(self) -> None:
        if not getattr(self._settings, "STRATEGY_ENABLED", True):
            return
        names = _parse_strategy_list(getattr(self._settings, "STRATEGY_SET", "ema_atr"))
        if not names:
            names = ["ema_atr"]
        for n in names:
            self._add(n)

    async def decide(self, symbol: str) -> Signal:
        """
        Агрегация решений стратегий согласно STRATEGY_MODE:
        - first: вернуть первый 'buy'/'sell';
        - vote:  голосование (порог по min_confidence);
        - weighted: сумма весов*confidence по направлениям.
        """
        if not self._strategies:
            return Signal(action="hold", reason="no_strategies")

        # Сбор решений
        results: List[Tuple[str, Decision]] = []
        for name, strat in self._strategies:
            ctx = StrategyContext(symbol=symbol, settings=self._settings)
            sig = await strat.generate(md=self._md, ctx=ctx)
            results.append((name, sig))
            if self._wcfg.mode == "first" and sig.action in ("buy", "sell") and dec(str(sig.confidence)) >= self._wcfg.min_confidence:
                return sig

        if self._wcfg.mode == "first":
            return Signal(action="hold", reason="all_hold")

        # vote / weighted
        buy_score = dec("0")
        sell_score = dec("0")
        buys = sells = 0

        for name, sig in results:
            conf = dec(str(sig.confidence or 0))
            if conf < self._wcfg.min_confidence:
                continue
            w = self._wcfg.weights.get(name, dec("1"))
            if self._wcfg.mode == "vote":
                if sig.action == "buy":
                    buys += 1
                elif sig.action == "sell":
                    sells += 1
            else:  # weighted
                if sig.action == "buy":
                    buy_score += w * conf
                elif sig.action == "sell":
                    sell_score += w * conf

        if self._wcfg.mode == "vote":
            if buys > sells:
                return Signal(action="buy", confidence=0.5, reason=f"vote:{buys}>{sells}")
            if sells > buys:
                return Signal(action="sell", confidence=0.5, reason=f"vote:{sells}>{buys}")
            return Signal(action="hold", reason="vote_tie")

        # weighted
        if buy_score > sell_score:
            return Signal(action="buy", confidence=float(min(dec("0.9"), buy_score / (buy_score + sell_score + dec("1e-9")))), reason="weighted")
        if sell_score > buy_score:
            return Signal(action="sell", confidence=float(min(dec("0.9"), sell_score / (buy_score + sell_score + dec("1e-9")))), reason="weighted")
        return Signal(action="hold", reason="weighted_tie")
