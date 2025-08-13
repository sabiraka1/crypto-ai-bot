# src/crypto_ai_bot/trading/bot.py
"""
🤖 Trading Bot Orchestrator (enhanced, signals-native)
- Чистые абсолютные импорты
- Dependency Injection через Deps
- Выравнивание цикла по границе таймфрейма (UTC)
- EventBus-адаптер (on/emit или subscribe/publish)
- Graceful stop с join()
- Интеграция сигналов: aggregator → validator → fusion → entry_policy
"""

from __future__ import annotations

import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import pandas as pd

# ── Абсолютные импорты из пакета ─────────────────────────────────────────────
from crypto_ai_bot.config.settings import Settings
from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.trading.exchange_client import ExchangeClient
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager

# Метрики (graceful-fallback — если prometheus_client не установлен, это no-op)
from crypto_ai_bot.core.metrics import (
    TRADING_LOOPS, SIGNALS_TOTAL, ENTRY_ATTEMPTS,
    POSITIONS_OPENED, POSITIONS_CLOSED, POSITIONS_OPEN_GAUGE,
    LAST_SCORE, ATR_PCT, DECISION_LATENCY,
)

# (оставляем для фоллбэков/совместимости — можно удалить, если не используете)
from crypto_ai_bot.analysis.scoring_engine import ScoringEngine  # noqa: F401
from crypto_ai_bot.analysis.technical_indicators import get_unified_atr

# Телеграм/CSV — на будущее
from crypto_ai_bot.telegram.api_utils import send_message  # noqa: F401
from crypto_ai_bot.utils.csv_handler import CSVHandler  # noqa: F401

# Сигналы (новые модули)
from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
from crypto_ai_bot.trading.signals.signal_validator import validate_features
from crypto_ai_bot.trading.signals.score_fusion import fuse_scores
from crypto_ai_bot.trading.signals.entry_policy import decide_entry

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Имя событий в одном месте ────────────────────────────────────────────────
EV_NEW_CANDLE = "new_candle"
EV_SIGNAL = "signal_generated"
EV_ENTRY_ATTEMPT = "entry_attempt"
EV_POS_OPENED = "position_opened"
EV_POS_CLOSED = "position_closed"
EV_RISK_ALERT = "risk_alert"
EV_BOT_STOPPING = "bot_stopping"


# ── DI-контейнер зависимостей ────────────────────────────────────────────────
@dataclass
class Deps:
    settings: Settings
    exchange: ExchangeClient
    state: StateManager
    risk: RiskManager
    positions: PositionManager
    events: EventBus


# ── Утилиты ──────────────────────────────────────────────────────────────────
def ohlcv_to_df(ohlcv) -> pd.DataFrame:
    """CCXT-like OHLCV → pandas DataFrame с индексом UTC datetime."""
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna()


def timeframe_minutes(tf: str) -> int:
    """Парсим '15m' | '1h' | '4h' → минуты (по умолчанию 15)."""
    try:
        s = tf.strip().lower()
        if s.endswith("m"):
            return int(s[:-1])
        if s.endswith("h"):
            return int(s[:-1]) * 60
        if s.endswith("d"):
            return int(s[:-1]) * 60 * 24
    except Exception:
        pass
    return 15


def unified_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Безопасный ATR с fallback на средний диапазон."""
    try:
        val = get_unified_atr(df, period, method="ewm")
        return float(val) if val is not None else None
    except Exception as e:
        logger.warning(f"[ATR] fallback, reason: {e}")
        try:
            return float((df["high"] - df["low"]).mean()) if not df.empty else None
        except Exception:
            return None


# ── Оркестратор ──────────────────────────────────────────────────────────────
class TradingBot:
    """
    Главный координатор торгового цикла:
    - сбор данных → агрегатор → валидатор → фьюжн → энтри-полиси → исполнение
    - событийная шина для интеграций (телеграм/метрики)
    """

    def __init__(self, deps: Deps):
        self.d = deps
        self.cfg = deps.settings

        # Основные параметры
        self.symbol: str = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        self.timeframe: str = getattr(self.cfg, "TIMEFRAME", "15m")
        self.cycle_minutes: int = int(getattr(self.cfg, "ANALYSIS_INTERVAL", timeframe_minutes(self.timeframe)))

        # Состояние
        self._running = False
        self._lock = threading.RLock()
        self._last_candle_id: Optional[str] = None
        self._last_info_log_ts = 0.0
        self._thread: Optional[threading.Thread] = None

        # Компоненты
        self.exchange = deps.exchange
        self.state = deps.state
        self.risk = deps.risk
        self.positions = deps.positions
        self.events = deps.events

        # (оставляем ScoringEngine только как резерв — сейчас не используется напрямую)
        self.scorer = ScoringEngine()

        # ИИ-модель (опционально)
        self.ml_model = None
        self.ml_ready = False
        self._init_ai_model()

        # Подписки на события
        self._setup_event_handlers()

        logger.info("🤖 TradingBot initialized (signals-native)")

    # ── EventBus adapter (поддержка on/emit и subscribe/publish) ──────────────
    def _bus_on(self, name: str, fn) -> None:
        if hasattr(self.events, "on"):
            self.events.on(name, fn)
        else:
            self.events.subscribe(name, fn)

    def _bus_emit(self, name: str, payload: Optional[dict] = None) -> None:
        if hasattr(self.events, "emit"):
            self.events.emit(name, payload or {})
        else:
            self.events.publish(name, payload or {})

    # ── Инициализация компонентов ────────────────────────────────────────────
    def _init_ai_model(self):
        ai_enabled = bool(getattr(self.cfg, "AI_ENABLE", False))
        if not ai_enabled:
            logger.info("🔲 AI disabled")
            return
        try:
            from crypto_ai_bot.ml.adaptive_model import AdaptiveMLModel
            models_dir = getattr(self.cfg, "MODELS_DIR", "models")
            self.ml_model = AdaptiveMLModel(models_dir=models_dir)
            if hasattr(self.ml_model, "load_models"):
                self.ml_model.load_models()
            self.ml_ready = True
            logger.info("🧠 AI model loaded")
        except Exception as e:
            logger.warning(f"⚠️ AI init failed: {e}")
            self.ml_model = None
            self.ml_ready = False

    def _setup_event_handlers(self):
        self._bus_on(EV_NEW_CANDLE, self._on_new_candle)
        self._bus_on(EV_SIGNAL, self._on_signal_generated)
        self._bus_on(EV_POS_OPENED, self._on_position_opened)
        self._bus_on(EV_POS_CLOSED, self._on_position_closed)
        self._bus_on(EV_RISK_ALERT, self._on_risk_alert)
        logger.info("📡 Event handlers bound")

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            logger.warning("⚠️ Bot already running")
            return
        logger.info("🚀 Bot starting…")
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="TradingLoop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            logger.info("🔲 Bot is not running")
            return
        logger.info("🛑 Bot stopping…")
        self._running = False
        self._bus_emit(EV_BOT_STOPPING, {})
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("✅ Bot stopped")

    # ── Loop ─────────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        logger.info("🔄 Trading loop started")
        # Первое выравнивание — до ближайшей границы ТФ
        self._sleep_until_next_bar()
        while self._running:
            TRADING_LOOPS.inc()  # ← счётчик итераций цикла
            try:
                self._cycle()
            except Exception as e:
                logger.error(f"❌ Trading cycle error: {e}", exc_info=True)
            # Ждём до следующей закрывшейся свечи, без дрейфа
            self._sleep_until_next_bar()
        logger.info("🔄 Trading loop finished")

    def _sleep_until_next_bar(self) -> None:
        tf_sec = self.cycle_minutes * 60
        now = int(time.time())
        # сколько секунд до ближайшей границы таймфрейма по UTC
        secs = tf_sec - (now % tf_sec)
        if secs < 1:
            secs += tf_sec
        max_secs = int(os.getenv("MAX_SLEEP_SECS", str(secs)))  # для отладки можно ограничить
        time.sleep(min(secs, max_secs))

    # ── Один торговый цикл ───────────────────────────────────────────────────
    def _cycle(self) -> None:
        with self._lock:
            # 1) Данные рынка (для события/мониторинга)
            df, last_price, atr_val = self._fetch_market_data()
            if df.empty or last_price is None:
                logger.warning("⚠️ No market data")
                return

            # 2) Событие «новая свеча»
            self._bus_emit(EV_NEW_CANDLE, {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "price": last_price,
                "atr": atr_val,
                "dataframe": df,
            })

            # 3) Уже в позиции? → ведём позицию и выходим
            if self._is_position_active():
                self._manage_position(last_price, atr_val or 0.0)
                return

            # 4) Не повторяем решение на той же свече
            candle_id = self._candle_id(df)
            if candle_id == self._last_candle_id:
                logger.debug(f"⏩ Same candle {candle_id}, skipping")
                return

            # 5) Анализ → сигнал → вход (таймим end-to-end)
            t0 = time.perf_counter()
            self._analyze_and_decide(df, last_price, atr_val)
            DECISION_LATENCY.observe(time.perf_counter() - t0)

            # 6) Запомнить обработанную свечу
            self._last_candle_id = candle_id

    # ── Данные ───────────────────────────────────────────────────────────────
    def _fetch_market_data(self) -> Tuple[pd.DataFrame, Optional[float], Optional[float]]:
        try:
            # поддержим оба варианта клиента: get_ohlcv() или fetch_ohlcv()
            if hasattr(self.exchange, "get_ohlcv"):
                ohlcv = self.exchange.get_ohlcv(self.symbol, timeframe=self.timeframe, limit=200)
            else:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe=self.timeframe, limit=200)  # type: ignore[attr-defined]
            df = ohlcv_to_df(ohlcv)
            if df.empty:
                return pd.DataFrame(), None, None
            last_price = float(df["close"].iloc[-1])
            atr_val = unified_atr(df)
            return df, last_price, atr_val
        except Exception as e:
            logger.error(f"❌ fetch_market_data failed: {e}", exc_info=True)
            return pd.DataFrame(), None, None

    # ── Анализ и решение ─────────────────────────────────────────────────────
    def _analyze_and_decide(self, df: pd.DataFrame, price: float, atr_val: Optional[float]) -> None:
        """
        Новый конвейер:
        aggregator → validator → fusion → entry_policy → attempt_entry
        """
        try:
            # 0) AI-скор (если включен)
            ai_score = self._predict_ai_score(df)

            # 1) Сбор фич (15m/1h/4h, индикаторы, контекст summary)
            feats = aggregate_features(self.cfg, self.exchange, ctx={})
            if "error" in feats:
                logger.warning(f"⚠️ Aggregator returned error: {feats.get('error')}")
                return

            # Подменяем ai_score на реальный из модели (если был посчитан)
            feats["ai_score"] = float(ai_score)

            # 2) Валидация (ATR%, ликвидность, мультифрейм 4h, stale и т.д.)
            ok, reasons = validate_features(self.cfg, self.state, feats)
            if not ok:
                self._bus_emit(EV_SIGNAL, {
                    "symbol": self.symbol,
                    "price": price,
                    "buy_score": 0.0,
                    "ai_score": ai_score,
                    "atr": atr_val,
                    "details": {"validation_failed": reasons},
                })
                logger.info(f"❎ Signal rejected by validator: {reasons}")
                return

            # 3) Fusion (adaptive by default) — учитываем качество данных и «волу»
            ind = feats.get("indicators", {})
            atr_pct = None
            try:
                atr = ind.get("atr"); p = ind.get("price")
                atr_pct = (atr / p) * 100 if atr and p else None
            except Exception:
                pass
            market_vol = "high" if atr_pct and atr_pct > float(getattr(self.cfg, "ATR_PCT_MAX", 10.0)) else "normal"

            fusion_strategy = str(getattr(self.cfg, "FUSION_STRATEGY", "adaptive")).lower()
            fusion_cfg = {
                "alpha": float(getattr(self.cfg, "FUSION_ALPHA", 0.6)),
                "conflict_threshold": float(getattr(self.cfg, "FUSION_CONFLICT_THRESHOLD", 0.3)),
                "consensus_threshold": float(getattr(self.cfg, "FUSION_CONSENSUS_THRESHOLD", 0.6)),
            }
            fusion_ctx = {"data_quality": feats.get("data_quality", {}), "market_volatility": market_vol}
            fusion = fuse_scores(float(feats["rule_score"]), float(feats["ai_score"]),
                                 strategy=fusion_strategy, config=fusion_cfg, context=fusion_ctx)

            fused_score = float(fusion.final_score)
            feats["fusion"] = fusion.__dict__
            feats["confidence"] = fusion.confidence
            feats["conflict_detected"] = bool(fusion.conflict_detected)

            # 4) Логи/метрики и событие «сигнал»
            market_condition = _mk_condition_from_indicators(ind)
            # gauge: последний скор и ATR% (если можем посчитать)
            try: LAST_SCORE.set(max(0.0, min(1.0, fused_score)))
            except: pass
            try:
                if atr_val and price:
                    ATR_PCT.set(float(atr_val) / float(price) * 100.0)
            except: pass

            self._log_market_info(fused_score, float(feats["ai_score"]), atr_val, {"market_condition": market_condition})
            self._bus_emit(EV_SIGNAL, {
                "symbol": self.symbol,
                "price": price,
                "buy_score": fused_score,
                "ai_score": float(feats["ai_score"]),
                "atr": atr_val,
                "details": {
                    "market_condition": market_condition,
                    "fusion": feats["fusion"],
                    "context_summary": feats.get("context_summary"),
                    "indicators": {k: ind.get(k) for k in ("rsi","atr","atr_pct","ema20","ema50","ema9","ema21","macd_hist","volume_ratio","trend_4h_bull")},
                },
            })

            # 5) Принятие решения об входе
            decision = decide_entry(self.cfg, self.state, self.risk, feats, fused_score)
            if not decision.get("enter"):
                logger.info(f"❎ Entry denied: {decision.get('reason')}")
                return

            # 6) Попытка входа (детали SL/TP передаём в позиционник)
            size_usd = float(decision.get("size_usd", 0.0))
            payload = {
                "symbol": self.symbol,
                "price": price,
                "buy_score": fused_score,
                "ai_score": float(feats["ai_score"]),
                "position_size": size_usd,
                "entry_price": decision.get("entry_price"),
                "stop_loss": decision.get("stop_loss"),
                "take_profit": decision.get("take_profit"),
                "confidence": decision.get("confidence"),
                "reason": decision.get("reason"),
                "details": {
                    "threshold_used": decision.get("threshold_used"),
                    "sizing_details": decision.get("sizing_details"),
                    "decision_factors": decision.get("decision_factors"),
                },
            }
            ENTRY_ATTEMPTS.inc()  # ← фиксируем попытку входа
            self._bus_emit(EV_ENTRY_ATTEMPT, payload)

            if hasattr(self.positions, "open"):
                self.positions.open({
                    "symbol": self.symbol,
                    "side": "buy",  # лонг-режим
                    "size_usd": size_usd,
                    "entry_price": decision.get("entry_price") or price,
                    "stop_loss": decision.get("stop_loss"),
                    "take_profit": decision.get("take_profit"),
                    "context": payload,
                })

        except Exception as e:
            logger.error(f"❌ analyze_and_decide failed: {e}", exc_info=True)

    def _predict_ai_score(self, df: pd.DataFrame) -> float:
        if not getattr(self.cfg, "AI_ENABLE", False) or not self.ml_ready or self.ml_model is None:
            return float(getattr(self.cfg, "AI_FAILOVER_SCORE", 0.5))
        try:
            # TODO: Подключить реальный инференс модели
            return float(getattr(self.cfg, "AI_FAILOVER_SCORE", 0.5))
        except Exception as e:
            logger.error(f"❌ AI prediction failed: {e}")
            return float(getattr(self.cfg, "AI_FAILOVER_SCORE", 0.5))

    # ── Управление позицией / вход ───────────────────────────────────────────
    def _is_position_active(self) -> bool:
        try:
            st = getattr(self.state, "state", {}) or {}
            return bool(st.get("in_position") or st.get("opening"))
        except Exception as e:
            logger.error(f"❌ state check failed: {e}")
            # консервативно считаем, что позиция есть → не открываем новую
            return True

    def _manage_position(self, price: float, atr_val: float) -> None:
        try:
            if hasattr(self.positions, "manage"):
                self.positions.manage(price=price, atr=atr_val)
        except Exception as e:
            logger.error(f"❌ manage_position failed: {e}")

    # ── Вспомогательное ──────────────────────────────────────────────────────
    @staticmethod
    def _candle_id(df: pd.DataFrame) -> str:
        try:
            return df.index[-1].strftime("%Y%m%d_%H%M") if not df.empty else ""
        except Exception:
            return ""

    def _log_market_info(self, buy_score: float, ai_score: float, atr_val: Optional[float], details: dict) -> None:
        now = time.time()
        min_interval = int(os.getenv("INFO_LOG_INTERVAL_SEC", "300"))
        if now - self._last_info_log_ts >= min_interval:
            market_condition = details.get("market_condition", "n/a")
            atr_txt = f"{atr_val:.6f}" if atr_val is not None else "N/A"
            logger.info(f"📊 Market: {market_condition}")
            logger.info(
                f"📊 Score: {buy_score:.2f}/{float(getattr(self.cfg,'MIN_SCORE_TO_BUY',0.65)):.2f} | "
                f"AI: {ai_score:.2f} | ATR: {atr_txt}"
            )
            self._last_info_log_ts = now

    # ── Event handlers (с метриками) ─────────────────────────────────────────
    def _on_new_candle(self, data: dict):
        logger.debug(f"📊 New candle: {data.get('symbol')} @ {data.get('price')}")

    def _on_signal_generated(self, data: dict):
        SIGNALS_TOTAL.inc()
        logger.debug(f"🎯 Signal emitted: score={data.get('buy_score')}, ai={data.get('ai_score')}")

    def _on_position_opened(self, data: dict):
        POSITIONS_OPENED.inc()
        POSITIONS_OPEN_GAUGE.inc()
        logger.info(f"📥 Position opened: {data}")

    def _on_position_closed(self, data: dict):
        POSITIONS_CLOSED.inc()
        POSITIONS_OPEN_GAUGE.dec()
        logger.info(f"📤 Position closed: {data}")

    def _on_risk_alert(self, data: dict):
        logger.warning(f"⚠️ Risk alert: {data}")


# ── helpers ──────────────────────────────────────────────────────────────────
def _mk_condition_from_indicators(ind: Dict[str, Any]) -> str:
    try:
        if ind.get("trend_4h_bull") is True:
            return "bull_4h"
        if ind.get("trend_4h_bull") is False:
            return "bear_4h"
        if ind.get("ema20", 0) > ind.get("ema50", 0):
            return "bull_15m"
        if ind.get("ema20", 0) < ind.get("ema50", 0):
            return "bear_15m"
    except Exception:
        pass
    return "sideways"


__all__ = ["TradingBot", "Deps"]
