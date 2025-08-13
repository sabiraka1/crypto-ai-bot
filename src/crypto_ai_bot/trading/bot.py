# src/crypto_ai_bot/trading/bot.py
"""
🤖 Trading Bot (safe/live)
- Единый цикл анализа и принятия решений
- SAFE_MODE: paper-trading с реальными данными (виртуальные сделки, логи в CSV)
- LIVE: реальная торговля через ExchangeClient/PositionManager
"""

from __future__ import annotations

import os
import time
import json
import math
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import pandas as pd

# ── Конфиг/ядро ──────────────────────────────────────────────────────────────
try:
    from crypto_ai_bot.config.settings import Settings
except Exception:  # совместимость со старым импортом
    from ..config.settings import Settings  # type: ignore

from crypto_ai_bot.core.state_manager import StateManager
from crypto_ai_bot.core.events import EventBus
from crypto_ai_bot.core.metrics import metrics  # не обязателен, но если есть — хорошо

# ── Трейдинг ────────────────────────────────────────────────────────────────
from crypto_ai_bot.trading.exchange_client import ExchangeClient, APIException
from crypto_ai_bot.trading.position_manager import PositionManager
from crypto_ai_bot.trading.risk_manager import RiskManager

# ── Сигналы / скоринг ──────────────────────────────────────────────────────
from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features
from crypto_ai_bot.trading.signals.signal_validator import validate_features
from crypto_ai_bot.trading.signals.score_fusion import fuse_scores
from crypto_ai_bot.trading.signals.entry_policy import should_enter_long

# ── Вспомогательное ────────────────────────────────────────────────────────
try:
    from crypto_ai_bot.analysis.technical_indicators import get_unified_atr
except Exception:
    # лёгкий фолбэк на случай, если модуль недоступен
    def get_unified_atr(df: pd.DataFrame, period: int = 14, method: str = "ewm") -> Optional[float]:
        if df is None or df.empty:
            return None
        tr = (df["high"] - df["low"]).abs()
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1]) if "high" in df and "low" in df else None

try:
    from crypto_ai_bot.telegram.api_utils import send_message
except Exception:
    def send_message(text: str) -> None:
        logging.getLogger(__name__).info("[telegram disabled] %s", text)

try:
    from crypto_ai_bot.utils.csv_handler import CSVHandler
except Exception:
    class CSVHandler:
        @staticmethod
        def append(path: str, row: Dict[str, Any]) -> None:
            # минимальный фолбэк
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            exists = os.path.exists(path)
            df = pd.DataFrame([row])
            df.to_csv(path, mode="a", index=False, header=not exists, encoding="utf-8")


logger = logging.getLogger(__name__)


# ── DI контейнер ────────────────────────────────────────────────────────────
@dataclass
class Deps:
    settings: Settings
    exchange: ExchangeClient
    state: StateManager
    risk: RiskManager
    positions: PositionManager
    events: EventBus


# ── Утилиты ────────────────────────────────────────────────────────────────
def ohlcv_to_df(ohlcv: List[List[float]]) -> pd.DataFrame:
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(how="any")


# ── Бот ────────────────────────────────────────────────────────────────────
class TradingBot:
    def __init__(self, deps: Deps):
        self.deps = deps
        self.cfg = deps.settings

        self.symbol = self.cfg.SYMBOL
        self.timeframe = self.cfg.TIMEFRAME
        self.cycle_minutes = int(os.getenv("ANALYSIS_INTERVAL", self.cfg.ANALYSIS_INTERVAL))

        self._is_running = False
        self._lock = threading.RLock()
        self._last_decision_candle: Optional[str] = None
        self._last_info_ts: float = 0.0

        self.exchange = deps.exchange
        self.state = deps.state
        self.risk = deps.risk
        self.positions = deps.positions
        self.events = deps.events

        self._init_ai()
        self._bind_events()

        logger.info("🤖 TradingBot initialized (signals-native)")

    # ── Инициализация ИИ ───────────────────────────────────────────────────
    def _init_ai(self) -> None:
        self.ml = None
        self.ai_ready = False
        if not self.cfg.AI_ENABLE:
            logger.info("🔲 AI disabled")
            return
        try:
            from crypto_ai_bot.ml.adaptive_model import AdaptiveMLModel
            self.ml = AdaptiveMLModel(models_dir=os.getenv("MODEL_DIR", "models"))
            if hasattr(self.ml, "load_models"):
                self.ml.load_models()
            self.ai_ready = True
            logger.info("🧠 AI model ready")
        except Exception as e:
            logger.warning("⚠️ AI init failed: %s", e)

    # ── События ────────────────────────────────────────────────────────────
    def _bind_events(self) -> None:
        self.events.on("new_candle", self._on_new_candle)
        self.events.on("signal_generated", self._on_signal)
        self.events.on("position_opened", self._on_pos_opened)
        self.events.on("position_closed", self._on_pos_closed)
        self.events.on("risk_alert", self._on_risk)
        logger.info("📡 Event handlers bound")

    # ── Жизненный цикл ─────────────────────────────────────────────────────
    def start(self) -> None:
        if self._is_running:
            logger.warning("already running")
            return
        logger.info("🚀 Bot starting…")
        self._is_running = True
        t = threading.Thread(target=self._loop, name="TradingLoop", daemon=True)
        t.start()

    def stop(self) -> None:
        if not self._is_running:
            return
        logger.info("🛑 Bot stopping…")
        self._is_running = False

    # ── Основной цикл ──────────────────────────────────────────────────────
    def _loop(self) -> None:
        logger.info("🔄 Trading loop started")
        while self._is_running:
            try:
                self._cycle()
            except Exception as e:
                logger.error("cycle error: %s", e, exc_info=True)
            time.sleep(self.cycle_minutes * 60)
        logger.info("🔄 Trading loop ended")

    def _cycle(self) -> None:
        with self._lock:
            # 1) Данные
            df_15m, last_price, atr_val = self._fetch_market()
            if df_15m.empty or last_price is None:
                return

            # 2) Событие свечи
            self.events.emit("new_candle", {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "price": last_price,
                "atr": atr_val,
            })

            # 3) Ведение позиции, если открыта
            if self._has_open_position():
                self._manage_position(last_price, atr_val or 0.0)
                return

            # 4) Один раз на свечу
            candle_id = df_15m.index[-1].strftime("%Y%m%d_%H%M")
            if self._last_decision_candle == candle_id:
                return

            # 5) Аналитика → решение
            self._analyze_and_decide(df_15m, last_price, atr_val)
            self._last_decision_candle = candle_id

    # ── Данные рынка ───────────────────────────────────────────────────────
    def _fetch_market(self) -> Tuple[pd.DataFrame, Optional[float], Optional[float]]:
        try:
            ohlcv = self.exchange.get_ohlcv(self.symbol, timeframe=self.timeframe, limit=200)
            df = ohlcv_to_df(ohlcv)
            if df.empty:
                return pd.DataFrame(), None, None
            price = float(df["close"].iloc[-1])
            atr = get_unified_atr(df, period=int(os.getenv("ATR_PERIOD", "14")), method=os.getenv("RISK_ATR_METHOD", "ewm"))
            return df, price, atr
        except Exception as e:
            logger.error("fetch market failed: %s", e)
            return pd.DataFrame(), None, None

    # ── Аналитика и вход ───────────────────────────────────────────────────
    def _analyze_and_decide(self, df_15m: pd.DataFrame, last_price: float, atr_val: Optional[float]) -> None:
        try:
            # a) агрегируем фичи на 15m/1h/4h + контекст
            feats = aggregate_features(
                exchange=self.exchange,
                symbol=self.symbol,
                timeframes=[self.timeframe, "1h", "4h"],
                limit=200
            )

            # b) валидация фичей (ликвидность/спред/объём и т.п.)
            valid_ok, vreason = validate_features(feats, price=last_price)
            if not valid_ok:
                self._log_info(buy_score=0.0, ai_score=self._ai(df_15m), atr_val=atr_val, details={"reason": vreason})
                return

            # c) rule score (RSI/MACD/EMA/ATR/объёмы + контекст штрафы/бонусы)
            rule_score, details = fuse_scores(feats, ai_score=None)  # AI добавим отдельным полем

            # d) AI score
            ai_score = self._ai(df_15m)

            # e) лог/ивенты
            self._log_info(buy_score=rule_score, ai_score=ai_score, atr_val=atr_val, details=details)
            payload = {
                "symbol": self.symbol,
                "price": last_price,
                "buy_score": float(rule_score),
                "ai_score": float(ai_score),
                "atr": float(atr_val) if atr_val is not None else None,
                "details": details
            }
            self.events.emit("signal_generated", payload)

            # f) гейт по правилам входа (включая мультифрейм/контекстные проверки)
            if not should_enter_long(rule_score, ai_score, self.cfg.MIN_SCORE_TO_BUY, self.cfg.AI_MIN_TO_TRADE, self.cfg.ENFORCE_AI_GATE):
                return

            # g) размер позиции (простой вариант: TRADE_AMOUNT * f(ai))
            qty_usd = self._position_usd(ai_score)

            # h) риск-менеджмент / стопы
            sl_pct = float(os.getenv("STOP_LOSS_PCT", "2.0")) / 100.0  # например 2%
            tp_pct = float(os.getenv("TAKE_PROFIT_PCT", "1.5")) / 100.0
            sl_price = last_price * (1.0 - sl_pct)
            tp_price = last_price * (1.0 + tp_pct)

            # i) вход (safe → виртуально; live → позиционер)
            self._enter_long(price=last_price, qty_usd=qty_usd, sl=sl_price, tp=tp_price, context=details)

            # j) CSV-лог снапшота сигнала
            self._log_signal_csv(rule_score, ai_score, last_price, details)

        except Exception as e:
            logger.error("analysis/decision failed: %s", e, exc_info=True)

    # ── AI score ────────────────────────────────────────────────────────────
    def _ai(self, df_15m: pd.DataFrame) -> float:
        # Вставь свою реальную подготовку фич сюда, если модель требует
        if not self.cfg.AI_ENABLE or not self.ai_ready or self.ml is None:
            return float(self.cfg.AI_FAILOVER_SCORE)
        try:
            if hasattr(self.ml, "predict"):
                score = float(self.ml.predict(df_15m))
                if math.isnan(score) or score < 0 or score > 1:
                    return float(self.cfg.AI_FAILOVER_SCORE)
                return score
        except Exception as e:
            logger.warning("AI predict failed: %s", e)
        return float(self.cfg.AI_FAILOVER_SCORE)

    # ── Размер позиции ─────────────────────────────────────────────────────
    def _position_usd(self, ai_score: float) -> float:
        pos_min = float(os.getenv("POSITION_MIN_FRACTION", "0.30"))
        pos_max = float(os.getenv("POSITION_MAX_FRACTION", "1.00"))
        thr = float(self.cfg.MIN_SCORE_TO_BUY)
        base = float(os.getenv("TRADE_AMOUNT", self.cfg.TRADE_AMOUNT))
        # линейная шкала от thr..1 → pos_min..pos_max
        frac = pos_min + max(0.0, (ai_score - thr) / max(1e-9, (1 - thr))) * (pos_max - pos_min)
        frac = min(max(frac, pos_min), pos_max)
        return base * frac

    # ── Вход (safe/live) ───────────────────────────────────────────────────
    def _enter_long(self, price: float, qty_usd: float, sl: float, tp: float, context: Dict[str, Any]) -> None:
        safe = bool(int(os.getenv("SAFE_MODE", "1")))
        try:
            if safe:
                # ── ВИРТУАЛЬНЫЙ ВХОД ──────────────────────────────────────
                self._paper_open(price, qty_usd, sl, tp, context)
            else:
                # ── РЕАЛЬНЫЙ ВХОД (если реализован в PositionManager) ────
                if hasattr(self.positions, "open_market"):
                    pos = self.positions.open_market(symbol=self.symbol, side="buy", usd_amount=qty_usd, sl=sl, tp=tp, context=context)
                    self.events.emit("position_opened", {"symbol": self.symbol, "price": price, "qty_usd": qty_usd, "mode": "live", "extra": pos})
                else:
                    # если нет метода — fallback на paper, чтобы не терять сделку
                    logger.warning("open_market not found in PositionManager; fallback to paper")
                    self._paper_open(price, qty_usd, sl, tp, context)
        except Exception as e:
            logger.error("entry failed: %s", e, exc_info=True)

    # ── Paper-trading реализация ───────────────────────────────────────────
    def _paper_open(self, price: float, qty_usd: float, sl: float, tp: float, context: Dict[str, Any]) -> None:
        equity = float(os.getenv("PAPER_EQUITY", "1000"))
        qty = qty_usd / max(1e-9, price)
        self.state.state.update({
            "in_position": True,
            "position_side": "long",
            "entry_price": price,
            "entry_time": time.time(),
            "qty": qty,
            "usd_amount": qty_usd,
            "sl": sl,
            "tp": tp,
            "paper": True,
            "context": context,
            "equity": equity,
        })
        self.events.emit("position_opened", {"symbol": self.symbol, "price": price, "qty_usd": qty_usd, "mode": "paper"})
        send_message(f"📥 [PAPER] LONG {self.symbol}\n@ {price:.4f}\nSL {sl:.4f} / TP {tp:.4f}\n${qty_usd:.2f}")

    # ── Ведение позиции (safe/live) ────────────────────────────────────────
    def _has_open_position(self) -> bool:
        try:
            st = self.state.state
            return bool(st.get("in_position"))
        except Exception:
            return False

    def _manage_position(self, last_price: float, atr: float) -> None:
        st = self.state.state
        is_paper = bool(st.get("paper", False))
        entry = float(st.get("entry_price", 0.0))
        sl = float(st.get("sl", 0.0))
        tp = float(st.get("tp", 0.0))
        qty = float(st.get("qty", 0.0))
        usd_amount = float(st.get("usd_amount", 0.0))

        # выход по SL/TP
        closed = None
        reason = None
        if last_price <= sl:
            closed = sl
            reason = "STOP"
        elif last_price >= tp:
            closed = tp
            reason = "TAKE"

        # тайм-аут (опционально)
        max_minutes = int(os.getenv("MAX_MINUTES_IN_TRADE", "480"))  # 8 часов по умолчанию
        if closed is None and time.time() - float(st.get("entry_time", time.time())) > max_minutes * 60:
            closed = last_price
            reason = "TIMEOUT"

        if closed is None:
            return

        pnl = (closed - entry) * qty
        self._close_position(price=closed, pnl=pnl, usd_amount=usd_amount, reason=reason, paper=is_paper)

    def _close_position(self, price: float, pnl: float, usd_amount: float, reason: str, paper: bool) -> None:
        st = self.state.state
        entry = float(st.get("entry_price", 0.0))
        qty = float(st.get("qty", 0.0))
        data = {
            "symbol": self.symbol,
            "side": "long",
            "entry_price": entry,
            "exit_price": price,
            "qty": qty,
            "usd_amount": usd_amount,
            "pnl_abs": pnl,
            "pnl_pct": (pnl / max(1e-9, usd_amount)),
            "reason": reason,
            "paper": paper,
            "ts_close": time.time(),
        }

        # очистка состояния
        st.update({"in_position": False})

        # лог + событие + CSV
        self.events.emit("position_closed", data)
        msg_mode = "PAPER" if paper else "LIVE"
        send_message(f"📤 [{msg_mode}] EXIT {self.symbol} {reason}\n@ {price:.4f} | PnL ${pnl:.2f}")
        self._log_closed_csv(data)

    # ── Логирование ────────────────────────────────────────────────────────
    def _log_info(self, buy_score: float, ai_score: float, atr_val: Optional[float], details: Dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_info_ts < int(os.getenv("INFO_LOG_INTERVAL_SEC", "300")):
            return
        market_condition = details.get("market_condition", "SIDEWAYS")
        logger.info(
            "📊 Score: rule=%.3f thr=%.2f | AI=%.3f minAI=%.2f | ATR=%s | regime=%s",
            buy_score,
            self.cfg.MIN_SCORE_TO_BUY,
            ai_score,
            self.cfg.AI_MIN_TO_TRADE,
            f"{atr_val:.6f}" if atr_val is not None else "N/A",
            market_condition,
        )
        try:
            metrics.gauge("rule_score", buy_score)
            metrics.gauge("ai_score", ai_score)
        except Exception:
            pass
        self._last_info_ts = now

    def _log_signal_csv(self, rule_score: float, ai_score: float, price: float, details: Dict[str, Any]) -> None:
        path = os.getenv("SIGNALS_CSV", "signals_snapshots.csv")
        row = {
            "ts": time.time(),
            "symbol": self.symbol,
            "price": price,
            "rule_score": float(rule_score),
            "ai_score": float(ai_score),
            "details": json.dumps(details, ensure_ascii=False),
        }
        try:
            CSVHandler.append(path, row)
        except Exception as e:
            logger.warning("signal csv append failed: %s", e)

    def _log_closed_csv(self, data: Dict[str, Any]) -> None:
        path = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
        try:
            CSVHandler.append(path, data)
        except Exception as e:
            logger.warning("closed csv append failed: %s", e)

    # ── Обработчики событий ────────────────────────────────────────────────
    def _on_new_candle(self, payload: Dict[str, Any]) -> None:
        logger.debug("new candle: %s @ %.6f", payload.get("symbol"), payload.get("price", 0.0))

    def _on_signal(self, payload: Dict[str, Any]) -> None:
        logger.debug("signal: rule=%.3f ai=%.3f", payload.get("buy_score", 0.0), payload.get("ai_score", 0.0))

    def _on_pos_opened(self, payload: Dict[str, Any]) -> None:
        logger.info("position opened: %s", payload)

    def _on_pos_closed(self, payload: Dict[str, Any]) -> None:
        logger.info("position closed: %s", payload)

    def _on_risk(self, payload: Dict[str, Any]) -> None:
        logger.warning("risk alert: %s", payload)


__all__ = ["TradingBot", "Deps"]
