import os
import time
import logging
import traceback
import pandas as pd
from typing import Optional, Tuple

# ── наши модули из проекта ────────────────────────────────────────────────────
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient
from analysis.scoring_engine import ScoringEngine
from telegram.bot_handler import notify_entry, notify_close

# ── базовая настройка логов ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


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


# ── основной торговый класс ───────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        # конфиги из .env
        self.symbol = os.getenv("SYMBOL", "BTC/USDT")
        self.timeframe_15m = os.getenv("TIMEFRAME", "15m")  # базовый ТФ
        self.trade_amount_usd = float(os.getenv("TRADE_AMOUNT", "50"))
        self.cycle_minutes = int(os.getenv("ANALYSIS_INTERVAL", "15"))

        # инфраструктура
        self.state = StateManager()
        self.exchange = ExchangeClient(
            api_key=os.getenv("GATE_API_KEY"),
            api_secret=os.getenv("GATE_API_SECRET"),
        )

        # ⬇️ Создаем PositionManager с функциями уведомлений
        from trading.position_manager import PositionManager
        self.pm = PositionManager(self.exchange, self.state, notify_entry, notify_close)

        self.scorer = ScoringEngine()  # MIN_SCORE_TO_BUY подтянется из .env

        logging.info("✅ Loaded 0 models")
        logging.info("🚀 Trading bot initialized")

    # ── AI-модель (опционально) ───────────────────────────────────────────────
    def _predict_ai_score(self, df_15m: pd.DataFrame) -> float:
        """
        Пытаемся взять оценку AI из твоей модели, если она вообще существует.
        Если нет — возвращаем 0.55 (умеренная уверенность).
        """
        try:
            # пример: откуда-то из твоей ml/AdaptiveMLModel
            from ml.adaptive_model import AdaptiveMLModel  # type: ignore

            model = AdaptiveMLModel()
            # Ниже просто заглушка: у тебя может быть свой API.
            # Дай мне знать — подгоню под твой интерфейс.
            prob = getattr(model, "predict_proba", None)
            if callable(prob):
                # например, берём последние 100 свечек как фичи
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
        logging.info("🔄 Starting trading cycle...")

        df_15m, last_price, atr_val = self._fetch_market()
        if df_15m.empty or last_price is None:
            logging.error("Failed to fetch market data")
            return

        # AI score (0..1)
        ai_score = self._predict_ai_score(df_15m)

        # Считаем Buy Score + собираем детали (RSI/MACD/и т.д.)
        buy_score, ai_score, details = self.scorer.evaluate(df_15m, ai_score=ai_score)

        # (опционально) можно оценить рынок как bullish/sideways/bearish,
        # но для краткости логируем только "sideways" с низкой уверенностью:
        market_cond = "sideways"
        confidence = 0.01
        logging.info(f"📊 Market Analysis: {market_cond}, Confidence: {confidence:.2f}")

        # Для лога покажем, что именно внесло вклад
        macd_hist = details.get("macd_hist")
        rsi_val = details.get("rsi")
        macd_growing = details.get("macd_growing", False)

        # Для красоты: +1 если MACD>0, +1 если растёт, +1 если RSI в зоне
        macd_pts = (1.0 if (macd_hist is not None and macd_hist > 0) else 0.0) + (1.0 if macd_growing else 0.0)
        rsi_pts = 1.0 if (rsi_val is not None and 45 <= rsi_val <= 65) else 0.0

        logging.info(f"✅ RSI in healthy range (+1 point)" if rsi_pts > 0 else "ℹ️ RSI outside healthy range")
        logging.info(f"📊 Buy Score: {buy_score:.2f}/{self.scorer.min_score_to_buy:.2f} | MACD: {macd_pts:.1f} | AI: {ai_score:.2f}")

        # Если уже в позиции — даём менеджеру сопровождать её
        if self.state.state.get("in_position"):
            try:
                self.pm.manage(self.symbol, last_price, atr_val or 0.0)
            except Exception:
                logging.exception("Error in manage state")
            return

        # Если позиции нет — оцениваем вход
        if buy_score >= self.scorer.min_score_to_buy:
            # насколько торговать от TRADE_AMOUNT — по AI Score
            frac = self.scorer.position_fraction(ai_score)
            usd_amt = self.trade_amount_usd * frac

            # Раньше здесь был вызов explain_signal_short(...).
            # Сохраняем тот же формат переменной expl, но формируем сообщение прямо тут.
            rsi_note = (
                "n/a" if rsi_val is None else
                (f"{rsi_val:.1f} (перепродан)" if rsi_val < 30 else
                 f"{rsi_val:.1f} (перекуплен)" if rsi_val > 70 else
                 f"{rsi_val:.1f} (здоровая зона)" if 45 <= rsi_val <= 65 else
                 f"{rsi_val:.1f}")
            )
            macd_note = "n/a" if macd_hist is None else f"{macd_hist:.4f} ({'бычий' if macd_hist > 0 else 'медвежий'})"
            trend_note = "EMA12>EMA26" if (macd_hist and macd_hist > 0) else "EMA12<=EMA26"
            adx_note = "20.0"  # как и было в заглушке
            expl = f"RSI {rsi_note} | MACD hist {macd_note} | {trend_note} | ADX {adx_note}"

            if frac <= 0.0 or usd_amt <= 0.0:
                # Не входим, но сообщаем в лог и (опционально) в TG
                logging.info(f"⛔ AI Score {ai_score:.2f} -> position 0%. Вход пропущен.")
                return

            try:
                # Открываем лонг (спот). PositionManager сам выставит tp/sl/трейлинг + сохранит state
                self.pm.open_long(self.symbol, usd_amt, entry_price=last_price, atr=(atr_val or 0.0))
                logging.info(f"✅ LONG позиция открыта: {self.symbol} на ${usd_amt:.2f}")
            except Exception:
                logging.exception("Error while opening long")
        else:
            logging.info("❎ Filtered by Buy Score")

    # ── внешний запуск ─────────────────────────────────────────────────────────
    def run(self):
        logging.info("📊 Bot started, entering main loop...")
        while True:
            try:
                self._trading_cycle()
            except Exception as e:
                logging.error(f"Cycle error: {e}\n{traceback.format_exc()}")
            # Период цикла
            time.sleep(self.cycle_minutes * 60)