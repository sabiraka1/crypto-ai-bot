# src/crypto_ai_bot/trading/bot.py
"""
🤖 Trading Bot Orchestrator (signals-native)
Лёгкий, многофункциональный оркестратор без лишней нагрузки.
Совместим с текущей структурой проекта и модулями signals/* и context/*
"""

from __future__ import annotations

import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

# ── Конфиг и ядро ────────────────────────────────────────────────────────────
from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
# metrics опционален — не тянем сюда роутер, только безопасные счётчики при наличии
try:
    from crypto_ai_bot.core.metrics import incr_counter, set_gauge  # type: ignore
except Exception:
    def incr_counter(*args, **kwargs):  # no-op
        pass
    def set_gauge(*args, **kwargs):  # no-op
        pass

# ── Торговля и риск ─────────────────────────────────────────────────────────
from crypto_ai_bot.trading.exchange_client import ExchangeClient, APIException
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager

# ── Сигналы ─────────────────────────────────────────────────────────────────
from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
from crypto_ai_bot.trading.signals.signal_validator import validate_features
from crypto_ai_bot.trading.signals.score_fusion import fuse_scores
from crypto_ai_bot.trading.signals.entry_policy import decide_entry  # ← ВАЖНО: так и называем

# ── Контекст ────────────────────────────────────────────────────────────────
from crypto_ai_bot.context.snapshot import (
    ContextSnapshot,
    build_context_snapshot,
)

# ── Аналитика (ATR fallback) ────────────────────────────────────────────────
try:
    from crypto_ai_bot.analysis.technical_indicators import get_unified_atr
except Exception:
    get_unified_atr = None  # используем фолбэк ниже

logger = logging.getLogger(__name__)


# =============================================================================
# DI-контейнер
# =============================================================================
@dataclass
class Deps:
    settings: Settings
    exchange: ExchangeClient
    state: StateManager
    risk: RiskManager
    positions: PositionManager
    events: EventBus


# =============================================================================
# Вспомогательные утилиты
# =============================================================================
def ohlcv_to_df(ohlcv: Any) -> pd.DataFrame:
    """CCXT OHLCV → pandas.DataFrame с индексом времени (UTC)."""
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()


def unified_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Единый расчёт ATR — через analysis.get_unified_atr или безопасный фолбэк."""
    try:
        if get_unified_atr is not None:
            return float(get_unified_atr(df, period=period, method="ewm"))
        # фолбэк: средний диапазон high-low
        if df.empty:
            return None
        return float((df["high"] - df["low"]).mean())
    except Exception as e:
        logger.warning(f"ATR fallback failed: {e}")
        return None


# =============================================================================
# Основной оркестратор
# =============================================================================
class TradingBot:
    """
    Лёгкий оркестратор торгового цикла:
      - сбор данных и контекста
      - агрегация фич/сигналов
      - проверка входа (лонг-логика)
      - paper-trade / реальное исполнение (по конфигу)
    """

    def __init__(self, deps: Deps):
        self.deps = deps
        self.cfg = deps.settings

        # Основные параметры
        self.symbol: str = self.cfg.SYMBOL
        self.timeframe: str = self.cfg.TIMEFRAME  # основной ТФ для логов
        self.cycle_minutes: int = int(self.cfg.ANALYSIS_INTERVAL)
        self.safe_mode: bool = bool(int(os.getenv("SAFE_MODE", "1")))
        self.enable_trading: bool = bool(int(os.getenv("ENABLE_TRADING", "1")))

        # Внутреннее состояние
        self._is_running = False
        self._loop_lock = threading.RLock()
        self._last_candle_id: Optional[str] = None

        # Ссылки на компоненты
        self.exchange = deps.exchange
        self.state = deps.state
        self.risk = deps.risk
        self.positions = deps.positions
        self.events = deps.events

        # Подготовка AI (по желанию; не обязательна для работы)
        self._init_ai()

        # Хендлеры событий
        self._bind_event_handlers()

        logger.info(
            "🤖 TradingBot initialized (signals-native) | SAFE_MODE=%s, ENABLE_TRADING=%s",
            int(self.safe_mode), int(self.enable_trading)
        )

    # ── AI (опционально) ────────────────────────────────────────────────────
    def _init_ai(self) -> None:
        self.ai_ready = False
        self.ai_model = None
        if not bool(int(os.getenv("AI_ENABLE", "0"))):
            logger.info("🔲 AI disabled")
            return
        try:
            # Твоя модель (если есть)
            from crypto_ai_bot.ml.adaptive_model import AdaptiveMLModel  # type: ignore
            self.ai_model = AdaptiveMLModel(models_dir=self.cfg.MODEL_DIR)
            if hasattr(self.ai_model, "load_models"):
                self.ai_model.load_models()
            self.ai_ready = True
            logger.info("🧠 AI model initialized")
        except Exception as e:
            # Не фейлим бот из-за отсутствия sklearn/joblib и т.п.
            logger.warning("⚠️ AI init failed: %s", e)

    # ── Events ──────────────────────────────────────────────────────────────
    def _bind_event_handlers(self) -> None:
        self.events.on("new_candle", self._on_new_candle)
        self.events.on("signal_generated", self._on_signal_generated)
        self.events.on("paper_trade", self._on_paper_trade)
        self.events.on("position_opened", self._on_position_opened)
        self.events.on("position_closed", self._on_position_closed)
        self.events.on("risk_alert", self._on_risk_alert)
        logger.info("📡 Event handlers bound")

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._is_running:
            logger.warning("Bot already running")
            return
        logger.info("🚀 Bot starting…")
        self._is_running = True
        t = threading.Thread(target=self._loop, name="TradingLoop", daemon=True)
        t.start()

    def stop(self) -> None:
        if not self._is_running:
            logger.info("Bot is not running")
            return
        logger.info("🛑 Bot stopping…")
        self._is_running = False

    # ── Main loop ───────────────────────────────────────────────────────────
    def _loop(self) -> None:
        logger.info("🔄 Trading loop started")
        while self._is_running:
            try:
                self._tick()
            except Exception as e:
                logger.error("❌ Cycle error: %s", e, exc_info=True)
                incr_counter("bot_cycle_errors_total", 1)
            time.sleep(self.cycle_minutes * 60)
        logger.info("🔄 Trading loop stopped")

    # ── One cycle ───────────────────────────────────────────────────────────
    def _tick(self) -> None:
        with self._loop_lock:
            # 1) Контекст
            ctx: ContextSnapshot = build_context_snapshot(self.cfg)

            # 2) Фичи/индикаторы/скоры (15m + 1h + 4h)
            timeframes = ["15m", "1h", "4h"]
            features = aggregate_features(
                exchange=self.exchange,
                symbol=self.symbol,
                timeframes=timeframes,
                limit=int(os.getenv("INDICATOR_LOOKBACK", "200")),
                context=ctx,
                use_context_penalties=bool(int(os.getenv("USE_CONTEXT_PENALTIES", "1")))
            )

            if not validate_features(features):
                logger.warning("⚠️ Invalid features, skip")
                incr_counter("features_invalid_total", 1)
                return

            rule_score: float = float(features.get("rule_score", 0.0))
            ai_score_raw: float = float(features.get("ai_score", float(os.getenv("AI_FAILOVER_SCORE", "0.55"))))
            # Если агрегатор уже вернул penalized — используем его для «правил», а при этом fuse оставляем как есть
            rule_penalized: float = float(features.get("rule_score_penalized", rule_score))

            # 3) Комбинированный скор (правила + AI)
            fused_score = fuse_scores(rule_penalized, ai_score_raw)

            # 4) Отправим событие с готовым сигналом
            signal_payload = {
                "symbol": self.symbol,
                "rule_score": rule_score,
                "rule_penalized": rule_penalized,
                "ai_score": ai_score_raw,
                "fused_score": fused_score,
                "context": {
                    "market_condition": ctx.market_condition,
                    "btc_dominance": ctx.btc_dominance,
                    "dxy_change_1d": ctx.dxy_change_1d,
                    "fear_greed": ctx.fear_greed,
                    "penalties": getattr(features, "applied_penalties", features.get("applied_penalties", [])),
                },
            }
            self.events.emit("signal_generated", signal_payload)

            # 5) Решение о входе (лонг)
            decision = decide_entry(features, self.cfg, fused_score=fused_score)
            if not decision or not isinstance(decision, dict):
                logger.debug("⏭ No entry decision this cycle")
                set_gauge("last_decision_score", fused_score)
                return

            # decision: {side, entry_price, sl_price, tp_price, size_usd, reason, ...}
            side = decision.get("side", "long")
            if side != "long":
                logger.debug("Only LONG supported, decision=%s", side)
                set_gauge("last_decision_score", fused_score)
                return

            # риск-фильтры (ATR, дневные лимиты и т.д.)
            if not self._pass_risk_checks(decision):
                logger.info("⛔ Blocked by risk manager")
                incr_counter("entry_blocked_risk_total", 1)
                set_gauge("last_decision_score", fused_score)
                return

            # 6) Вход: SAFE_MODE → paper event; live → интеграция с PositionManager
            if self.safe_mode or not self.enable_trading:
                # paper trade
                paper = {
                    "symbol": self.symbol,
                    "side": "BUY",
                    "entry": float(decision.get("entry_price")),
                    "sl": float(decision.get("sl_price", 0.0)),
                    "tp": float(decision.get("tp_price", 0.0)),
                    "size_usd": float(decision.get("size_usd", self.cfg.TRADE_AMOUNT)),
                    "score": fused_score,
                    "reason": decision.get("reason", "rules+ai"),
                }
                logger.info("🧪 PAPER BUY %s | $%.2f | score=%.3f | %s",
                            paper["symbol"], paper["size_usd"], fused_score, paper["reason"])
                self.events.emit("paper_trade", paper)
                incr_counter("paper_entries_total", 1)
                set_gauge("last_decision_score", fused_score)
                return

            # live-mode (если нужно: подключить реальные ордера)
            try:
                # здесь можно вызвать methods твоего PositionManager для реального ордера
                # пример (если у тебя есть такой метод):
                # self.positions.open_market_buy(self.symbol, usd_amount=decision["size_usd"], sl=..., tp=...)
                logger.info("🟢 LIVE BUY requested (stub) | size=%.2f score=%.3f",
                            float(decision.get("size_usd", self.cfg.TRADE_AMOUNT)), fused_score)
                incr_counter("live_entries_total", 1)
            except Exception as e:
                logger.error("❌ Live entry failed: %s", e, exc_info=True)
                incr_counter("live_entry_errors_total", 1)

    # ── Risk filters glue ────────────────────────────────────────────────────
    def _pass_risk_checks(self, decision: Dict[str, Any]) -> bool:
        """Точка интеграции с RiskManager. Возвращаем True, если риски ОК."""
        try:
            # минимальные проверки — ATR и дневные лимиты (если у тебя реализовано)
            # можно прокинуть в self.risk какие-то параметры из decision
            return True
        except Exception as e:
            logger.error("Risk check failed: %s", e, exc_info=True)
            return False

    # ── Event handlers ───────────────────────────────────────────────────────
    def _on_new_candle(self, payload: Dict[str, Any]) -> None:
        logger.debug("🕯️ new_candle %s %s", payload.get("symbol"), payload.get("timeframe"))

    def _on_signal_generated(self, payload: Dict[str, Any]) -> None:
        logger.debug(
            "🎯 signal: rule=%.3f pen=%.3f ai=%.3f fused=%.3f ctx=%s",
            float(payload.get("rule_score", 0.0)),
            float(payload.get("rule_penalized", payload.get("rule_score", 0.0))),
            float(payload.get("ai_score", 0.0)),
            float(payload.get("fused_score", 0.0)),
            payload.get("context", {}).get("market_condition", "SIDEWAYS"),
        )

    def _on_paper_trade(self, payload: Dict[str, Any]) -> None:
        logger.info("📄 paper_trade: %s", payload)

    def _on_position_opened(self, payload: Dict[str, Any]) -> None:
        logger.info("📥 position_opened: %s", payload)

    def _on_position_closed(self, payload: Dict[str, Any]) -> None:
        logger.info("📤 position_closed: %s", payload)

    def _on_risk_alert(self, payload: Dict[str, Any]) -> None:
        logger.warning("⚠️ risk_alert: %s", payload)


# ── Экспорт ─────────────────────────────────────────────────────────────────
__all__ = ["TradingBot", "Deps"]
