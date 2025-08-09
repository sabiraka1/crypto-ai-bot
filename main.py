import os
import time
import logging
import traceback
import pandas as pd
from typing import Optional, Tuple

# ── наши модули из проекта ────────────────────────────────────────────────────
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient, APIException
from analysis.scoring_engine import ScoringEngine
from telegram import bot_handler as tgbot  # используем только send_message

# ── базовая настройка логов ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ── ENV-пороги и настроечки ───────────────────────────────────────────────────
ENV_MIN_SCORE = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))  # если scorer не перехватит — валидируем вручную
ENV_ENFORCE_AI_GATE = str(os.getenv("ENFORCE_AI_GATE", "1")).strip().lower() in ("1", "true", "yes", "on")
ENV_AI_MIN_TO_TRADE = float(os.getenv("AI_MIN_TO_TRADE", "0.70"))

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

        logging.info("✅ Loaded 0 models")
        logging.info("🚀 Trading bot initialized")

    # ── AI-модель (опционально) ───────────────────────────────────────────────
    def _predict_ai_score(self, df_15m: pd.DataFrame) -> float:
        """
        Пытаемся взять оценку AI из твоей модели, если она вообще существует.
        Если нет — возвращаем 0.55 (умеренная уверенность).
        """
        try:
            from ml.adaptive_model import AdaptiveMLModel  # type: ignore
            model = AdaptiveMLModel()
            prob = getattr(model, "predict_proba", None)
            if callable(prob):
                ai = float(prob(df_15m.tail(100)) or 0.55)
                return max(0.0, min(1.0, ai))
        except Exception:
            pass
        return 0.55

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

    # ── торговый цикл ─────────────────────────────────────────────────────────
    def _trading_cycle(self):
        df_15m, last_price, atr_val = self._fetch_market()
        if df_15m.empty or last_price is None:
            logging.error("Failed to fetch market data")
            return

        # Временная метка текущей (последней) свечи
        candle_ts = int(df_15m.index[-1].timestamp())
        last_seen = self.state.state.get("last_candle_ts")

        # Считаем все метрики (для логов и для решений)
        ai_score_raw = self._predict_ai_score(df_15m)
        buy_score, ai_score_eval, details = self.scorer.evaluate(df_15m, ai_score=ai_score_raw)
        ai_score = max(0.0, min(1.0, float(ai_score_eval if ai_score_eval is not None else ai_score_raw)))

        macd_hist = details.get("macd_hist")
        rsi_val = details.get("rsi")
        macd_growing = details.get("macd_growing", False)

        macd_pts = (1.0 if (macd_hist is not None and macd_hist > 0) else 0.0) + (1.0 if macd_growing else 0.0)
        rsi_pts = 1.0 if (rsi_val is not None and 45 <= rsi_val <= 65) else 0.0

        # ── Информационный лог каждые INFO_LOG_INTERVAL_SEC (не влияет на торговлю) ──
        now = time.time()
        if now - self._last_info_log_ts >= INFO_LOG_INTERVAL_SEC:
            market_cond = "sideways"  # тут можно подключить свою логику определения рынка
            confidence = 0.01
            logging.info(f"📊 Market Analysis: {market_cond}, Confidence: {confidence:.2f}")
            logging.info("✅ RSI in healthy range (+1 point)" if rsi_pts > 0 else "ℹ️ RSI outside healthy range")
            logging.info(
                f"📊 Buy Score: {buy_score:.2f}/{getattr(self.scorer, 'min_score_to_buy', ENV_MIN_SCORE):.2f} "
                f"| MACD: {macd_pts:.1f} | AI: {ai_score:.2f}"
            )
            self._last_info_log_ts = now

        # ── Управление открытой позицией делаем на каждом цикле ──
        if self.state.state.get("in_position"):
            try:
                self.pm.manage(self.symbol, last_price, atr_val or 0.0)
            except Exception:
                logging.exception("Error in manage state")

        # ── Решение «войти/нет» ТОЛЬКО по закрытию новой свечи ──
        # если это та же свеча, что уже обрабатывали — решения не принимаем
        if last_seen is not None and candle_ts == int(last_seen):
            return

        # Новая свеча: принимаем решение, а потом запоминаем её ts
        try:
            # 1) порог по buy_score
            min_thr = getattr(self.scorer, "min_score_to_buy", ENV_MIN_SCORE)
            if buy_score < float(min_thr):
                logging.info(f"❎ Filtered by Buy Score (score={buy_score:.2f} < {float(min_thr):.2f})")
                return

            # 2) AI gate (если включён)
            if ENV_ENFORCE_AI_GATE and (ai_score < ENV_AI_MIN_TO_TRADE):
                logging.info(f"⛔ AI gate: ai={ai_score:.2f} < {ENV_AI_MIN_TO_TRADE:.2f} → вход запрещён")
                try:
                    tgbot.send_message(
                        f"⛔ Вход отклонён AI-гейтом: ai={ai_score:.2f} < {ENV_AI_MIN_TO_TRADE:.2f}"
                    )
                except Exception:
                    pass
                return

            # 3) размер позиции
            frac = self.scorer.position_fraction(ai_score)  # 0..1
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
                return

            # 4) попытка входа (PM сам поднимет до min_notional и не даст двойной вход)
            try:
                self.pm.open_long(
                    self.symbol,
                    usd_planned,
                    entry_price=last_price,
                    atr=(atr_val or 0.0),
                    buy_score=buy_score,
                    ai_score=ai_score,
                    amount_frac=frac,
                )
                logging.info(f"✅ LONG позиция открыта: {self.symbol} на ${usd_planned:.2f}")
            except APIException as e:
                logging.warning(f"💤 Биржа отклонила вход: {e}")
                try:
                    tgbot.send_message(f"💤 Вход отклонён биржей: {e}")
                except Exception:
                    pass
            except Exception:
                logging.exception("Error while opening long")
                try:
                    tgbot.send_message("❌ Ошибка при открытии позиции (см. логи)")
                except Exception:
                    pass
        finally:
            # Запоминаем обработанную свечу в любом случае, чтобы не принимать решение повторно
            try:
                self.state.state["last_candle_ts"] = candle_ts
                self.state.save_state()
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
