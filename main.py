import os
import time
import logging
import traceback
import threading
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import numpy as np

# ── наши модули из проекта ────────────────────────────────────────────────────
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient, APIException
from analysis.scoring_engine import ScoringEngine
from telegram import bot_handler as tgbot  # используем только send_message
from utils.csv_handler import CSVHandler  # <-- добавлено

# ── базовая настройка логов ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ── ENV-пороги и настройка AI ─────────────────────────────────────────────────
ENV_MIN_SCORE = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))
ENV_ENFORCE_AI_GATE = str(os.getenv("ENFORCE_AI_GATE", "1")).strip().lower() in ("1", "true", "yes", "on")
ENV_AI_MIN_TO_TRADE = float(os.getenv("AI_MIN_TO_TRADE", "0.70"))

AI_ENABLE = str(os.getenv("AI_ENABLE", "1")).strip().lower() in ("1", "true", "yes", "on")
AI_FAILOVER_SCORE = float(os.getenv("AI_FAILOVER_SCORE", "0.55"))

SYMBOL_DEFAULT = os.getenv("SYMBOL", "BTC/USDT")
TIMEFRAME_DEFAULT = os.getenv("TIMEFRAME", "15m")

# Интервал циклов и отдельный интервал для инфо-логов
ANALYSIS_INTERVAL_MIN = int(os.getenv("ANALYSIS_INTERVAL", "15"))         # как и раньше
INFO_LOG_INTERVAL_SEC = int(os.getenv("INFO_LOG_INTERVAL_SEC", "600"))    # каждые 10 минут по умолчанию


# ── утилиты преобразования OHLCV -> DataFrame ─────────────────────────────────
def ohlcv_to_df(ohlcv) -> pd.DataFrame:
    """
    CCXT OHLCV -> pandas DataFrame c колонками time, open, high, low, close, volume.
    Индекс — UTC datetime.
    """
    if not ohlcv:
        return pd.DataFrame()
    cols = ["time", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(ohlcv, columns=cols)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df.set_index("time", inplace=True)
    # приводим к float
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna()
    return df


def atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    ATR для risk-менеджмента. Требуются колонки: high, low, close.
    Возвращаем последнее значение ATR.
    """
    if df.empty or len(df) < period + 2:
        return None
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()
    val = float(atr_series.iloc[-1])
    return val


# ── простые индикаторы для фич ────────────────────────────────────────────────
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).rolling(period, min_periods=period).mean()
    roll_down = pd.Series(down, index=series.index).rolling(period, min_periods=period).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# ── Уведомления-адаптеры под текущий PositionManager ─────────────────────────
def _notify_entry_tg(symbol: str, entry_price: float, amount_usd: float,
                     tp_pct: float, sl_pct: float, tp1_atr: float, tp2_atr: float,
                     buy_score: float = None, ai_score: float = None, amount_frac: float = None):
    """Адаптер под сигнатуру notify_entry(...) из PositionManager."""
    parts = [f"📥 Вход LONG {symbol} @ {entry_price:.4f}"]
    parts.append(f"Сумма: ${amount_usd:.2f}")
    parts.append(f"TP%≈{tp_pct:.4f} | SL%≈{sl_pct:.4f}")
    parts.append(f"TP1≈{tp1_atr:.4f} | TP2≈{tp2_atr:.4f}")
    extra = []
    if buy_score is not None and ai_score is not None:
        extra.append(f"Score {buy_score:.2f} / AI {ai_score:.2f}")
    if amount_frac is not None:
        extra.append(f"Size {int(amount_frac * 100)}%")
    if extra:
        parts.append(" | ".join(extra))
    try:
        tgbot.send_message("\n".join(parts))
    except Exception:
        logging.exception("notify_entry send failed")


def _notify_close_tg(symbol: str, price: float, reason: str,
                     pnl_pct: float, pnl_abs: float = None,
                     buy_score: float = None, ai_score: float = None, amount_usd: float = None):
    """Адаптер под notify_close(...) текущей версии."""
    emoji = "✅" if (pnl_pct or 0) >= 0 else "❌"
    parts = [f"{emoji} Закрытие {symbol} @ {price:.4f}", f"{reason} | PnL {pnl_pct:.2f}%"]
    extra = []
    if pnl_abs is not None:
        extra.append(f"{pnl_abs:.2f}$")
    if amount_usd is not None:
        extra.append(f"Size ${amount_usd:.2f}")
    if buy_score is not None and ai_score is not None:
        extra.append(f"Score {buy_score:.2f} / AI {ai_score:.2f}")
    if extra:
        parts[-1] += f" ({' | '.join(extra)})"
    try:
        tgbot.send_message("\n".join(parts))
    except Exception:
        logging.exception("notify_close send failed")


# ── основной торговый класс ───────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        # конфиги из .env
        self.symbol = SYMBOL_DEFAULT
        self.timeframe_15m = TIMEFRAME_DEFAULT
        self.trade_amount_usd = float(os.getenv("TRADE_AMOUNT", "50"))
        self.cycle_minutes = ANALYSIS_INTERVAL_MIN

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Глобальная блокировка для торгового цикла
        self._trading_lock = threading.RLock()
        self._last_decision_candle = None  # Отслеживание последней обработанной свечи

        # инфраструктура
        self.state = StateManager()
        self.exchange = ExchangeClient(
            api_key=os.getenv("GATE_API_KEY"),
            api_secret=os.getenv("GATE_API_SECRET"),
        )

        # PositionManager (+ TG уведомления)
        from trading.position_manager import PositionManager
        self.pm = PositionManager(self.exchange, self.state, _notify_entry_tg, _notify_close_tg)

        # Скоуринг
        self.scorer = ScoringEngine()
        # если ScoringEngine поддерживает min_score, подменим на ENV
        try:
            if hasattr(self.scorer, "min_score_to_buy"):
                self.scorer.min_score_to_buy = ENV_MIN_SCORE
        except Exception:
            pass

        # Тикающий лог каждые INFO_LOG_INTERVAL_SEC
        self._last_info_log_ts = 0.0

        # ── AI модель (опциональная) ──────────────────────────────────────────
        self.ai_enabled = AI_ENABLE
        self.ai_failover = AI_FAILOVER_SCORE
        self.ml_model = None
        self.ml_ready = False
        if self.ai_enabled:
            try:
                from ml.adaptive_model import AdaptiveMLModel  # type: ignore
                # NB: у модели параметр называется models_dir
                self.ml_model = AdaptiveMLModel(models_dir="models")
                # если есть метод загрузки — вызовем
                if hasattr(self.ml_model, "load_models"):
                    try:
                        self.ml_model.load_models()
                    except Exception:
                        # если моделей нет — не критично, будем работать фолбэком
                        pass
                self.ml_ready = True
                logging.info("✅ AI model initialized")
            except Exception as e:
                self.ml_model = None
                self.ml_ready = False
                logging.warning(f"AI model not available: {e}")

        logging.info("🚀 Trading bot initialized")

    # ── построение фич для AI ─────────────────────────────────────────────────
    def _build_features(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Фичи строятся по ЗАКРЫТОЙ свече (t-1), чтобы избежать утечек будущего.
        Если данных мало — вернём пусто.
        """
        feats: Dict[str, Any] = {}
        try:
            if df is None or df.empty or len(df) < 60:
                return feats
            # работаем на копии
            x = df.copy()
            close = x["close"]

            # индикаторы
            rsi_14 = rsi(close, 14)
            macd_line, macd_sig, macd_hist = macd(close, 12, 26, 9)
            ema_20 = ema(close, 20)
            ema_50 = ema(close, 50)
            sma_20 = sma(close, 20)
            sma_50 = sma(close, 50)

            # изменения
            price_change_1 = close.pct_change(1)
            price_change_3 = close.pct_change(3)
            price_change_5 = close.pct_change(5)
            vol_change = x["volume"].pct_change(5)

            # ATR 14
            atr_val_series = self._series_atr(x, 14)

            # берем t-1
            feats = {
                "rsi": float(rsi_14.iloc[-2]) if not np.isnan(rsi_14.iloc[-2]) else None,
                "macd": float(macd_line.iloc[-2]),
                "macd_signal": float(macd_sig.iloc[-2]),
                "macd_hist": float(macd_hist.iloc[-2]),
                "ema_20": float(ema_20.iloc[-2]),
                "ema_50": float(ema_50.iloc[-2]),
                "sma_20": float(sma_20.iloc[-2]) if not np.isnan(sma_20.iloc[-2]) else None,
                "sma_50": float(sma_50.iloc[-2]) if not np.isnan(sma_50.iloc[-2]) else None,
                "atr_14": float(atr_val_series.iloc[-2]) if not np.isnan(atr_val_series.iloc[-2]) else None,
                "price_change_1": float(price_change_1.iloc[-2]) if not np.isnan(price_change_1.iloc[-2]) else None,
                "price_change_3": float(price_change_3.iloc[-2]) if not np.isnan(price_change_3.iloc[-2]) else None,
                "price_change_5": float(price_change_5.iloc[-2]) if not np.isnan(price_change_5.iloc[-2]) else None,
                "vol_change": float(vol_change.iloc[-2]) if not np.isnan(vol_change.iloc[-2]) else None,
                # простой маркер рыночного состояния (опционально)
                "market_condition": self._market_condition_guess(close.iloc[:-1]),
            }
        except Exception as e:
            logging.exception(f"Feature build failed: {e}")
        return feats

    def _series_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    def _market_condition_guess(self, close_series: pd.Series) -> str:
        # очень простой фильтр тренда: EMA20 vs EMA50
        try:
            e20 = ema(close_series, 20).iloc[-1]
            e50 = ema(close_series, 50).iloc[-1]
            if np.isnan(e20) or np.isnan(e50):
                return "sideways"
            if e20 > e50 * 1.002:
                return "bull"
            if e20 < e50 * 0.998:
                return "bear"
            return "sideways"
        except Exception:
            return "sideways"

    # ── AI-модель (оценка) ────────────────────────────────────────────────────
    def _predict_ai_score(self, df_15m: pd.DataFrame) -> float:
        """
        Стараемся получить уверенность модели в [0..1].
        Поддерживаем разные варианты API:
        - model.predict(features, market_condition) -> (pred, conf) | dict | float
        - model.predict_proba(features|df) -> float
        Фолбэк: AI_FAILOVER_SCORE.
        """
        try:
            if not self.ai_enabled or not self.ml_ready or self.ml_model is None:
                return self.ai_failover

            feats = self._build_features(df_15m)
            # если фич нет — фолбэк
            if not feats:
                return self.ai_failover

            # сначала пробуем современный predict(features, market_condition)
            if hasattr(self.ml_model, "predict"):
                try:
                    res = self.ml_model.predict(feats, feats.get("market_condition"))
                    # варианты результата:
                    if isinstance(res, tuple) and len(res) >= 2:
                        _, conf = res[0], res[1]
                        ai = float(conf)
                    elif isinstance(res, dict):
                        ai = float(res.get("confidence", self.ai_failover))
                    else:
                        ai = float(res)  # если вернули просто число
                    return max(0.0, min(1.0, ai))
                except Exception:
                    # падать не будем — попробуем predict_proba ниже
                    logging.debug("predict(...) failed, trying predict_proba(...)")

            # старый интерфейс: predict_proba(df | features)
            if hasattr(self.ml_model, "predict_proba"):
                try:
                    # некоторые реализации ожидают df/матрицу; дадим последние ~100 свечей
                    ai = self.ml_model.predict_proba(df_15m.tail(100))
                    ai = float(ai or self.ai_failover)
                    return max(0.0, min(1.0, ai))
                except Exception:
                    pass

        except Exception as e:
            logging.exception(f"AI predict failed: {e}")

        return self.ai_failover

    # ── получение рынка ────────────────────────────────────────────────────────
    def _fetch_market(self) -> Tuple[pd.DataFrame, Optional[float], Optional[float]]:
        """
        Загружаем 15m OHLCV, считаем ATR.
        Возвращаем: (df_15m, last_price, atr_val)
        """
        try:
            ohlcv_15m = self.exchange.fetch_ohlcv(self.symbol, timeframe=self.timeframe_15m, limit=200)
            df_15m = ohlcv_to_df(ohlcv_15m)
            if df_15m.empty:
                return pd.DataFrame(), None, None
            last_price = float(df_15m["close"].iloc[-1])
            atr_val = atr(df_15m)
            return df_15m, last_price, atr_val
        except Exception as e:
            logging.error(f"Failed to fetch market data: {e}")
            return pd.DataFrame(), None, None

    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка состояния позиции
    def _is_position_active(self) -> bool:
        """Безопасная проверка активности позиции"""
        try:
            with self._trading_lock:
                st = self.state.state
                return bool(st.get("in_position") or st.get("opening"))
        except Exception as e:
            logging.error(f"Error checking position state: {e}")
            return True  # В случае ошибки считаем что позиция активна для безопасности

    def _get_candle_id(self, df: pd.DataFrame) -> str:
        """Получает уникальный ID текущей свечи"""
        try:
            if df.empty:
                return ""
            return df.index[-1].strftime("%Y%m%d_%H%M")
        except Exception:
            return ""

    # ── торговый цикл ─────────────────────────────────────────────────────────
    def _trading_cycle(self):
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Глобальная блокировка торгового цикла
        with self._trading_lock:
            try:
                df_15m, last_price, atr_val = self._fetch_market()
                if df_15m.empty or last_price is None:
                    logging.error("Failed to fetch market data")
                    return

                # ✅ ПЕРВАЯ ПРОВЕРКА: Проверяем состояние позиции в самом начале
                if self._is_position_active():
                    logging.debug(f"💼 Position active, managing existing position")
                    # Только управляем существующей позицией
                    try:
                        self.pm.manage(self.symbol, last_price, atr_val or 0.0)
                    except Exception:
                        logging.exception("Error in manage state")
                    return  # ✅ ПРЕРЫВАЕМ цикл - не ищем новые входы

                # ✅ ПРОВЕРКА НОВОЙ СВЕЧИ: обрабатываем решения только по новым свечам
                current_candle_id = self._get_candle_id(df_15m)
                if current_candle_id == self._last_decision_candle:
                    logging.debug(f"⏩ Same candle {current_candle_id}, skipping decision logic")
                    return

                # Считаем все метрики (для логов и для решений)
                ai_score_raw = self._predict_ai_score(df_15m)
                buy_score, ai_score_eval, details = self.scorer.evaluate(df_15m, ai_score=ai_score_raw)
                ai_score = max(0.0, min(1.0, float(ai_score_eval if ai_score_eval is not None else ai_score_raw)))

                macd_hist = details.get("macd_hist")
                rsi_val = details.get("rsi")
                macd_growing = details.get("macd_growing", False)

                macd_pts = (1.0 if (macd_hist is not None and macd_hist > 0) else 0.0) + (1.0 if macd_growing else 0.0)
                rsi_pts = 1.0 if (rsi_val is not None and 45 <= rsi_val <= 65) else 0.0

                # ── Информационный лог каждые INFO_LOG_INTERVAL_SEC ──
                now = time.time()
                if now - self._last_info_log_ts >= INFO_LOG_INTERVAL_SEC:
                    market_cond_info = "sideways"
                    confidence = 0.01
                    try:
                        market_cond_info = details.get("market_condition", market_cond_info)
                        confidence = float(details.get("market_confidence", confidence))
                    except Exception:
                        pass
                    logging.info(f"📊 Market Analysis: {market_cond_info}, Confidence: {confidence:.2f}")
                    logging.info("✅ RSI in healthy range (+1 point)" if rsi_pts > 0 else "ℹ️ RSI outside healthy range")
                    logging.info(
                        f"📊 Buy Score: {buy_score:.2f}/{getattr(self.scorer, 'min_score_to_buy', ENV_MIN_SCORE):.2f} "
                        f"| MACD: {macd_pts:.1f} | AI: {ai_score:.2f}"
                    )
                    self._last_info_log_ts = now

                # ── Лог снимка сигнала (до принятия решения) ──
                try:
                    CSVHandler.log_signal_snapshot({
                        "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                        "symbol": self.symbol,
                        "timeframe": self.timeframe_15m,
                        "close": float(df_15m["close"].iloc[-1]),
                        "rsi": details.get("rsi"),
                        "macd": details.get("macd"),
                        "macd_signal": details.get("macd_signal"),
                        "macd_hist": details.get("macd_hist"),
                        "ema_20": details.get("ema_20"),
                        "ema_50": details.get("ema_50"),
                        "sma_20": details.get("sma_20"),
                        "sma_50": details.get("sma_50"),
                        "atr_14": details.get("atr"),
                        "price_change_1": details.get("price_change_1"),
                        "price_change_3": details.get("price_change_3"),
                        "price_change_5": details.get("price_change_5"),
                        "vol_change": details.get("vol_change"),
                        "buy_score": float(buy_score),
                        "ai_score": float(ai_score),
                        "market_condition": details.get("market_condition", "sideways"),
                        "decision": "precheck",
                        "reason": "periodic_snapshot"
                    })
                except Exception:
                    # не мешаем торговле, если лог не записался
                    pass

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Принятие решения только по новой свече
                try:
                    # ✅ ПЕРЕД КАЖДОЙ ПРОВЕРКОЙ: Убеждаемся что позиция НЕ активна
                    if self._is_position_active():
                        logging.info("⏩ Position became active during cycle, aborting entry logic")
                        self._last_decision_candle = current_candle_id
                        return

                    # 1) порог по buy_score
                    min_thr = getattr(self.scorer, "min_score_to_buy", ENV_MIN_SCORE)
                    if buy_score < float(min_thr):
                        logging.info(f"❎ Filtered by Buy Score (score={buy_score:.2f} < {float(min_thr):.2f})")
                        try:
                            CSVHandler.log_signal_snapshot({
                                "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                "symbol": self.symbol,
                                "timeframe": self.timeframe_15m,
                                "close": float(df_15m['close'].iloc[-1]),
                                "buy_score": float(buy_score),
                                "ai_score": float(ai_score),
                                "market_condition": details.get("market_condition", "sideways"),
                                "decision": "reject",
                                "reason": f"buy_score<{float(min_thr):.2f}",
                            })
                        except Exception:
                            pass
                        self._last_decision_candle = current_candle_id
                        return

                    # ✅ ПОВТОРНАЯ ПРОВЕРКА перед AI gate
                    if self._is_position_active():
                        logging.info("⏩ Position detected before AI gate, aborting")
                        self._last_decision_candle = current_candle_id
                        return

                    # 2) AI gate
                    if ENV_ENFORCE_AI_GATE and (ai_score < ENV_AI_MIN_TO_TRADE):
                        logging.info(f"⛔ AI gate: ai={ai_score:.2f} < {ENV_AI_MIN_TO_TRADE:.2f} → вход запрещён")
                        try:
                            tgbot.send_message(
                                f"⛔ Вход отклонён AI-гейтом: ai={ai_score:.2f} < {ENV_AI_MIN_TO_TRADE:.2f}"
                            )
                        except Exception:
                            pass
                        try:
                            CSVHandler.log_signal_snapshot({
                                "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                "symbol": self.symbol,
                                "timeframe": self.timeframe_15m,
                                "close": float(df_15m['close'].iloc[-1]),
                                "buy_score": float(buy_score),
                                "ai_score": float(ai_score),
                                "market_condition": details.get("market_condition", "sideways"),
                                "decision": "reject",
                                "reason": f"ai<{ENV_AI_MIN_TO_TRADE:.2f}",
                            })
                        except Exception:
                            pass
                        self._last_decision_candle = current_candle_id
                        return

                    # ✅ ПОВТОРНАЯ ПРОВЕРКА перед расчетом размера
                    if self._is_position_active():
                        logging.info("⏩ Position detected before position sizing, aborting")
                        self._last_decision_candle = current_candle_id
                        return

                    # 3) размер позиции
                    frac = self.scorer.position_fraction(ai_score)  # ожидается 0..1
                    usd_planned = float(self.trade_amount_usd) * float(frac)
                    min_cost = self.exchange.market_min_cost(self.symbol) or 0.0
                    logging.info(
                        f"SIZER: base={self.trade_amount_usd:.2f} ai={ai_score:.2f} "
                        f"-> planned={usd_planned:.2f}, min_cost={min_cost:.2f}"
                    )

                    if frac <= 0.0 or usd_planned <= 0.0:
                        msg = f"⛔ AI Score {ai_score:.2f} -> position 0%. Вход пропущен."
                        logging.info(msg)
                        try:
                            tgbot.send_message(msg)
                        except Exception:
                            pass
                        try:
                            CSVHandler.log_signal_snapshot({
                                "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                "symbol": self.symbol,
                                "timeframe": self.timeframe_15m,
                                "close": float(df_15m['close'].iloc[-1]),
                                "buy_score": float(buy_score),
                                "ai_score": float(ai_score),
                                "market_condition": details.get("market_condition", "sideways"),
                                "decision": "reject",
                                "reason": "position_fraction=0",
                            })
                        except Exception:
                            pass
                        self._last_decision_candle = current_candle_id
                        return

                    # ── market_condition / pattern из деталей или быстрый фолбэк ──
                    try:
                        market_condition = details.get("market_condition")
                    except Exception:
                        market_condition = None
                    try:
                        pattern = details.get("pattern") or details.get("setup") or ""
                    except Exception:
                        pattern = ""

                    if not market_condition:
                        try:
                            market_condition = self._market_condition_guess(df_15m["close"].iloc[:-1])
                        except Exception:
                            market_condition = "sideways"

                    # ✅ ФИНАЛЬНАЯ ПРОВЕРКА перед входом
                    if self._is_position_active():
                        logging.info("⏩ Final check: position active, canceling entry")
                        self._last_decision_candle = current_candle_id
                        return

                    # 4) попытка входа (PM сам поднимет до min_notional и не даст двойной вход)
                    try:
                        logging.info(f"🔒 Attempting to open position: {self.symbol} ${usd_planned:.2f}")
                        
                        result = self.pm.open_long(
                            self.symbol,
                            usd_planned,
                            entry_price=last_price,
                            atr=(atr_val or 0.0),
                            buy_score=buy_score,
                            ai_score=ai_score,
                            amount_frac=frac,
                            market_condition=market_condition,
                            pattern=pattern,
                        )
                        
                        if result is not None:
                            logging.info(f"✅ LONG позиция открыта: {self.symbol} на ${usd_planned:.2f}")
                            # лог входа в CSV
                            try:
                                CSVHandler.log_open_trade({
                                    "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                    "symbol": self.symbol,
                                    "side": "LONG",
                                    "entry_price": float(last_price),
                                    "qty_usd": float(usd_planned),
                                    "reason": "strategy_enter",
                                    "buy_score": float(buy_score),
                                    "ai_score": float(ai_score),
                                    "entry_ts": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                    "market_condition": market_condition,
                                    "pattern": pattern,
                                })
                            except Exception:
                                pass
                        else:
                            logging.warning("⚠️ Position opening returned None")

                    except APIException as e:
                        logging.warning(f"💤 Биржа отклонила вход: {e}")
                        try:
                            tgbot.send_message(f"💤 Вход отклонён биржей: {e}")
                        except Exception:
                            pass
                        try:
                            CSVHandler.log_signal_snapshot({
                                "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                "symbol": self.symbol,
                                "timeframe": self.timeframe_15m,
                                "close": float(df_15m['close'].iloc[-1]),
                                "buy_score": float(buy_score),
                                "ai_score": float(ai_score),
                                "market_condition": market_condition,
                                "decision": "reject",
                                "reason": f"exchange_reject:{e}",
                            })
                        except Exception:
                            pass
                    except Exception as e:
                        logging.exception("Error while opening long")
                        try:
                            tgbot.send_message("❌ Ошибка при открытии позиции (см. логи)")
                        except Exception:
                            pass
                        try:
                            CSVHandler.log_signal_snapshot({
                                "timestamp": df_15m.index[-1].isoformat().replace("+00:00", "Z"),
                                "symbol": self.symbol,
                                "timeframe": self.timeframe_15m,
                                "close": float(df_15m['close'].iloc[-1]),
                                "buy_score": float(buy_score),
                                "ai_score": float(ai_score),
                                "market_condition": market_condition,
                                "decision": "reject",
                                "reason": "exception_on_enter",
                            })
                        except Exception:
                            pass
                finally:
                    # ✅ КРИТИЧЕСКИ ВАЖНО: Запоминаем обработанную свечу в любом случае
                    self._last_decision_candle = current_candle_id

            except Exception as e:
                logging.error(f"Trading cycle error: {e}")
                # В случае критической ошибки тоже запоминаем свечу
                try:
                    if df_15m is not None and not df_15m.empty:
                        self._last_decision_candle = self._get_candle_id(df_15m)
                except Exception:
                    pass

    # ── внешний запуск ─────────────────────────────────────────────────────────
    def run(self):
        logging.info("📊 Bot started, entering main loop...")
        while True:
            try:
                self._trading_cycle()
            except Exception as e:
                logging.error(f"Cycle error: {e}\n{traceback.format_exc()}")
            time.sleep(self.cycle_minutes * 60)