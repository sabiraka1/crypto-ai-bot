# analysis/technical_indicators.py - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ

import time
import logging
import hashlib
import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict, Any
from functools import lru_cache

_EPS = 1e-12

# =============================================================================
# СИСТЕМА КЭШИРОВАНИЯ ИНДИКАТОРОВ
# =============================================================================

class IndicatorCache:
    """Кэш для технических индикаторов"""
    
    def __init__(self, ttl_seconds: int = 60, max_size: int = 100):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Tuple[pd.DataFrame, float]] = {}
        
    def get(self, cache_key: str) -> Optional[pd.DataFrame]:
        """Получить из кэша"""
        if cache_key not in self._cache:
            return None
            
        data, timestamp = self._cache[cache_key]
        if time.time() - timestamp > self.ttl:
            del self._cache[cache_key]
            return None
            
        return data.copy()
    
    def set(self, cache_key: str, data: pd.DataFrame):
        """Сохранить в кэш"""
        # Ограничиваем размер кэша
        if len(self._cache) >= self.max_size:
            # Удаляем самые старые записи
            oldest_keys = sorted(self._cache.keys(), 
                               key=lambda k: self._cache[k][1])[:10]
            for key in oldest_keys:
                del self._cache[key]
        
        self._cache[cache_key] = (data.copy(), time.time())
    
    def create_key(self, df: pd.DataFrame) -> str:
        """Создать ключ кэша из DataFrame"""
        if df.empty:
            return "empty"
        
        # Используем последние 10 строк + размер для ключа
        try:
            tail_data = df.tail(10)[['close', 'volume', 'high', 'low']].values
            data_str = f"{len(df)}_{str(tail_data)}"
            return hashlib.md5(data_str.encode()).hexdigest()[:16]
        except Exception:
            return f"fallback_{len(df)}_{time.time()}"
    
    def clear(self):
        """Очистить кэш"""
        self._cache.clear()
        logging.info("📊 Indicator cache cleared")

# Глобальный экземпляр кэша
_indicator_cache = IndicatorCache(ttl_seconds=60, max_size=50)

# =============================================================================
# БАЗОВЫЕ ФУНКЦИИ ИНДИКАТОРОВ (без изменений)
# =============================================================================

def _safe_tail_fill(s: pd.Series) -> pd.Series:
    """Заполняет только ХВОСТОВЫЕ NaN последним валидным значением"""
    if s is None or s.empty or not s.notna().any():
        return s
    last_valid = s.last_valid_index()
    if last_valid is None:
        return s
    pos = s.index.get_loc(last_valid)
    if isinstance(pos, slice):
        pos = pos.stop - 1
    start = pos + 1
    if start < len(s):
        s = s.copy()
        s.iloc[start:] = s.iloc[start:].fillna(s.iloc[pos])
    return s

def _to_f64(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("float64")

# =============================================================================
# ОПТИМИЗИРОВАННЫЕ РАСЧЕТЫ С ПОВТОРНЫМ ИСПОЛЬЗОВАНИЕМ
# =============================================================================

class IndicatorCalculator:
    """Калькулятор индикаторов с оптимизациями"""
    
    def __init__(self):
        self._ema_cache = {}  # Кэш для EMA различных периодов
        
    def calculate_emas(self, close: pd.Series, periods: list) -> Dict[int, pd.Series]:
        """Расчет множественных EMA за один проход"""
        result = {}
        for period in periods:
            cache_key = f"ema_{period}_{len(close)}"
            if cache_key in self._ema_cache:
                result[period] = self._ema_cache[cache_key]
            else:
                ema = close.ewm(span=period, adjust=False, min_periods=1).mean()
                self._ema_cache[cache_key] = ema
                result[period] = ema
        return result
    
    def calculate_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """Оптимизированный RSI"""
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        roll_up = gain.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
        roll_down = loss.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
        rs = roll_up / (roll_down + _EPS)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.astype("float64")
    
    def calculate_macd(self, close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        """Оптимизированный MACD"""
        # Используем уже рассчитанные EMA
        emas = self.calculate_emas(close, [fast, slow])
        macd = (emas[fast] - emas[slow]).astype("float64")
        macd_signal = macd.ewm(span=signal, adjust=False, min_periods=1).mean().astype("float64")
        macd_hist = (macd - macd_signal).astype("float64")
        return macd, macd_signal, macd_hist
    
    def calculate_bollinger(self, close: pd.Series, period: int = 20, num_std: float = 2.0):
        """Оптимизированные полосы Боллинджера"""
        # SMA уже может быть рассчитана
        sma = close.rolling(window=period, min_periods=1).mean()
        std = close.rolling(window=period, min_periods=1).std(ddof=0).fillna(0.0)
        upper = sma + num_std * std
        lower = sma - num_std * std
        
        # Позиция в диапазоне
        rng = (upper - lower)
        bb_position = ((close - lower) / (rng + _EPS)).clip(0.0, 1.0).astype("float64")
        
        return sma.astype("float64"), upper.astype("float64"), lower.astype("float64"), bb_position
    
    def clear_cache(self):
        """Очистить внутренний кэш"""
        self._ema_cache.clear()

# =============================================================================
# ГЛАВНАЯ ФУНКЦИЯ С КЭШИРОВАНИЕМ
# =============================================================================

def calculate_all_indicators(df: pd.DataFrame, use_cache: bool = True) -> pd.DataFrame:
    """
    ✅ ОПТИМИЗИРОВАННАЯ ВЕРСИЯ: Расчёт индикаторов с кэшированием и батчингом
    
    Features:
    - Умное кэширование результатов
    - Переиспользование промежуточных вычислений
    - Оптимизированные алгоритмы
    - Graceful обработка ошибок
    
    Args:
        df: DataFrame с колонками open, high, low, close, volume
        use_cache: Использовать кэширование (по умолчанию True)
        
    Returns:
        DataFrame с добавленными техническими индикаторами
    """
    start_time = time.time()
    
    if df is None or df.empty:
        logging.debug("📊 Technical indicators: empty DataFrame received")
        return pd.DataFrame()

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        logging.error(f"📊 Missing required columns: {missing}")
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    # Проверяем кэш
    if use_cache:
        cache_key = _indicator_cache.create_key(df)
        cached_result = _indicator_cache.get(cache_key)
        if cached_result is not None:
            logging.debug(f"📊 Cache hit for indicators, key: {cache_key[:8]}...")
            return cached_result

    logging.debug(f"📊 Calculating indicators for {len(df)} rows")

    try:
        out = df.copy()
        
        # Автоматическое приведение индекса к datetime
        if not isinstance(out.index, pd.DatetimeIndex):
            try:
                out.index = pd.to_datetime(out.index, utc=True, errors='coerce')
            except Exception as e:
                logging.debug(f"📊 Could not convert index to datetime: {e}")

        # Сортируем по времени
        try:
            out = out.sort_index()
        except Exception:
            pass

        # Приведение типов
        for c in ("open", "high", "low", "close", "volume"):
            out[c] = _to_f64(out[c])

        close = out["close"]
        high = out["high"] 
        low = out["low"]
        volume = out["volume"]

        # Создаем калькулятор для оптимизированных вычислений
        calc = IndicatorCalculator()

        # RSI
        out["rsi"] = _safe_tail_fill(calc.calculate_rsi(close, 14))

        # MACD + EMAs (оптимизированно)
        macd, macd_sig, macd_hist = calc.calculate_macd(close, 12, 26, 9)
        out["macd"] = _safe_tail_fill(macd)
        out["macd_signal"] = _safe_tail_fill(macd_sig)
        out["macd_hist"] = _safe_tail_fill(macd_hist)

        # Множественные EMA за один проход
        ema_periods = [12, 20, 26, 50, 200]
        emas = calc.calculate_emas(close, ema_periods)
        
        for period in ema_periods:
            out[f"ema_{period}"] = _safe_tail_fill(emas[period])
        
        # Алиасы для совместимости
        out["ema_fast"] = out["ema_12"]
        out["ema_slow"] = out["ema_26"]

        # SMA (только нужные)
        out["sma_50"] = _safe_tail_fill(close.rolling(50, min_periods=1).mean().astype("float64"))
        out["sma_200"] = _safe_tail_fill(close.rolling(200, min_periods=1).mean().astype("float64"))

        # Stochastic
        lowest_low = low.rolling(window=14, min_periods=1).min()
        highest_high = high.rolling(window=14, min_periods=1).max()
        rng = (highest_high - lowest_low)
        stoch_k = ((close - lowest_low) / (rng.replace(0, np.nan) + _EPS) * 100.0).clip(0.0, 100.0)
        stoch_d = stoch_k.rolling(window=3, min_periods=1).mean()
        
        out["stoch_k"] = _safe_tail_fill(stoch_k.astype("float64"))
        out["stoch_d"] = _safe_tail_fill(stoch_d.astype("float64"))

        # ADX (упрощенная версия)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean()

        plus_di = 100.0 * (plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean() / (atr + _EPS))
        minus_di = 100.0 * (minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean() / (atr + _EPS))
        dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + _EPS)).astype("float64")
        adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean()
        
        out["adx"] = _safe_tail_fill(adx.astype("float64"))
        out["atr"] = _safe_tail_fill(atr.astype("float64"))

        # Bollinger Bands (оптимизированные)
        bb_mid, bb_upper, bb_lower, bb_position = calc.calculate_bollinger(close, 20, 2.0)
        out["bb_mid"] = _safe_tail_fill(bb_mid)
        out["bb_upper"] = _safe_tail_fill(bb_upper)
        out["bb_lower"] = _safe_tail_fill(bb_lower)
        out["bb_position"] = _safe_tail_fill(bb_position)

        # Volume ratio
        v_sma = volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = (volume / (v_sma + _EPS)).astype("float64")
        out["volume_ratio"] = _safe_tail_fill(volume_ratio)

        # Гарантируем float64 для всех индикаторов
        indicator_cols = [col for col in out.columns if col not in df.columns]
        for col in indicator_cols:
            out[col] = _to_f64(out[col])

        # Очищаем внутренний кэш калькулятора
        calc.clear_cache()

        # Сохраняем в кэш
        if use_cache:
            _indicator_cache.set(cache_key, out)

        calc_time = time.time() - start_time
        logging.debug(f"📊 Indicators calculated in {calc_time:.3f}s, cached: {use_cache}")
        
        return out

    except Exception as e:
        logging.exception(f"Technical indicators calculation failed: {e}")
        return df.copy()

# =============================================================================
# УТИЛИТЫ ДЛЯ УПРАВЛЕНИЯ КЭШЕМ
# =============================================================================

def clear_indicator_cache():
    """Очистить кэш индикаторов"""
    _indicator_cache.clear()

def get_cache_stats() -> Dict[str, Any]:
    """Статистика кэша"""
    return {
        "size": len(_indicator_cache._cache),
        "max_size": _indicator_cache.max_size,
        "ttl_seconds": _indicator_cache.ttl,
        "keys": list(_indicator_cache._cache.keys())[:5]  # Первые 5 ключей
    }

# =============================================================================
# БЫСТРЫЕ ФУНКЦИИ ДЛЯ ОТДЕЛЬНЫХ ИНДИКАТОРОВ
# =============================================================================

@lru_cache(maxsize=128)
def quick_rsi(close_hash: str, period: int = 14) -> float:
    """Быстрый RSI для одного значения (с кэшированием)"""
    # Эта функция предназначена для использования с хэшированными данными
    # В реальном коде нужно передавать данные другим способом
    pass

def get_last_indicator_value(df: pd.DataFrame, indicator: str) -> Optional[float]:
    """Получить последнее значение индикатора"""
    try:
        indicators = calculate_all_indicators(df, use_cache=True)
        if indicator in indicators.columns:
            value = indicators[indicator].iloc[-1]
            return float(value) if pd.notna(value) else None
    except Exception as e:
        logging.error(f"Failed to get {indicator}: {e}")
    return None

# Экспорт для обратной совместимости
__all__ = [
    'calculate_all_indicators',
    'clear_indicator_cache', 
    'get_cache_stats',
    'get_last_indicator_value'
]