# analysis/technical_indicators.py - UNIFIED ATR + UNIFIED CACHE VERSION

from __future__ import annotations

import time
import logging
import hashlib
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache


_EPS = 1e-12

# ✅ UNIFIED CACHE INTEGRATION
try:
    from utils.unified_cache import get_cache_manager, CacheNamespace
    cache_manager = get_cache_manager()
    CACHE_AVAILABLE = True
    logging.info("📊 Technical Indicators: Unified Cache Manager loaded")
except ImportError as e:
    logging.warning(f"📊 Technical Indicators: Unified Cache not available, using fallback: {e}")
    cache_manager = None
    CACHE_AVAILABLE = False

# =============================================================================
# UNIFIED ATR FUNCTIONS - ЗАМЕНЯЕТ ВСЕ ДУБЛИРУЮЩИЕСЯ ATR В ПРОЕКТЕ
# =============================================================================

def get_unified_atr(df: pd.DataFrame, period: int = 14, method: str = 'ewm') -> Optional[float]:
    """
    ✅ UNIFIED ATR FUNCTION - Единая функция ATR для всего проекта
    
    Заменяет все дублирующиеся ATR функции в:
    - main.py → atr()
    - telegram/bot_handler.py → _atr()
    - risk_manager.py → _calculate_atr()
    - ml/adaptive_model.py → встроенная ATR
    - analysis/market_analyzer.py → встроенная ATR
    
    Args:
        df: DataFrame с колонками open, high, low, close, volume
        period: Период для расчета ATR (по умолчанию 14)
        method: 'ewm' (Exponential Weighted) или 'sma' (Simple Moving Average)
        
    Returns:
        float: ATR значение или None при ошибке
        
    Example:
        >>> df = pd.DataFrame({'high': [102, 103], 'low': [99, 100], 'close': [101, 102]})
        >>> atr_value = get_unified_atr(df, period=14, method='ewm')
        >>> print(f"ATR: {atr_value:.6f}")
    """
    
    if df is None or df.empty:
        logging.debug("📊 Unified ATR: empty DataFrame received")
        return None

    required_cols = {"high", "low", "close"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logging.error(f"📊 Unified ATR: missing columns {missing}")
        return None

    try:
        # Приведение типов с обработкой ошибок
        high = pd.to_numeric(df["high"], errors="coerce").ffill()
        low = pd.to_numeric(df["low"], errors="coerce").ffill()
        close = pd.to_numeric(df["close"], errors="coerce").ffill()
        
        # Проверяем достаточность данных
        min_periods = min(5, max(1, period // 3))  # Адаптивный минимум
        if len(df) < min_periods:
            logging.debug(f"📊 Unified ATR: insufficient data {len(df)} < {min_periods}")
            # Фолбэк: простая волатильность
            return float((high - low).mean()) if len(df) > 0 else None

        # True Range calculation (оптимизированная версия)
        prev_close = close.shift(1)
        
        # Vectorized True Range calculation
        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs() 
        tr3 = (low - prev_close).abs()
        
        # Efficient max calculation
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Handle edge cases
        tr = tr.fillna(tr1)  # Fallback to high-low if prev_close issues
        
        # ATR calculation based on method
        if method.lower() == 'sma':
            # Simple Moving Average method (для совместимости с risk_manager.py)
            atr_series = tr.rolling(window=period, min_periods=min_periods).mean()
        else:
            # Exponential Weighted Moving Average (по умолчанию, рекомендуется)
            alpha = 1.0 / period
            atr_series = tr.ewm(alpha=alpha, adjust=False, min_periods=min_periods).mean()
        
        # Получаем последнее значение
        if atr_series.empty or atr_series.isna().all():
            logging.debug("📊 Unified ATR: no valid ATR values calculated")
            return None
            
        atr_value = atr_series.iloc[-1]
        
        # Валидация результата
        if pd.isna(atr_value) or not np.isfinite(atr_value) or atr_value <= 0:
            logging.debug(f"📊 Unified ATR: invalid result {atr_value}")
            # Фолбэк к простому расчету
            return float(tr.mean()) if tr.notna().any() else None
            
        result = float(atr_value)
        logging.debug(f"📊 Unified ATR [{method}]: {result:.6f} (period={period}, data_len={len(df)})")
        
        return result

    except Exception as e:
        logging.error(f"📊 Unified ATR calculation failed: {e}")
        # Критический фолбэк
        try:
            simple_range = (df["high"] - df["low"]).mean()
            return float(simple_range) if pd.notna(simple_range) else None
        except Exception:
            return None


def atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    ✅ COMPATIBILITY ALIAS - Алиас для обратной совместимости
    
    Заменяет функцию atr() в main.py
    Использует EWM метод как стандарт
    """
    return get_unified_atr(df, period, method='ewm')


def _atr_for_telegram(df: pd.DataFrame, period: int = 14) -> float:
    """
    ✅ TELEGRAM COMPATIBILITY - Заменяет _atr() в bot_handler.py
    
    Возвращает float (не Optional) для совместимости с Telegram командами
    """
    result = get_unified_atr(df, period, method='ewm')
    return float(result) if result is not None else 0.0


def _atr_for_risk_manager(df: pd.DataFrame, period: Optional[int] = None) -> float:
    """
    ✅ RISK MANAGER COMPATIBILITY - Заменяет _calculate_atr() в risk_manager.py
    
    Поддерживает как EWM, так и SMA метод через env переменную
    По умолчанию использует EWM (более точный)
    """
    import os
    
    # Поддержка переключения метода через env
    atr_method = os.getenv("RISK_ATR_METHOD", "ewm").lower()  # ewm или sma
    period = period or int(os.getenv("ATR_PERIOD", 14))
    
    result = get_unified_atr(df, period, method=atr_method)
    
    # Risk manager ожидает float, не None
    if result is None:
        # Фолбэк для risk manager
        try:
            return float(df["close"].iloc[-1] * 0.02)  # 2% от цены
        except Exception:
            return 100.0  # Крайний фолбэк
            
    return float(result)


def _atr_series_for_ml(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ✅ ML MODEL COMPATIBILITY - Для ml/adaptive_model.py
    
    Возвращает Series для встраивания в ML feature engineering
    """
    try:
        if df is None or df.empty or len(df) < 2:
            return pd.Series([0.0] * len(df), index=df.index if not df.empty else [])

        # Используем тот же алгоритм что и в get_unified_atr
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce") 
        close = pd.to_numeric(df["close"], errors="coerce")
        
        prev_close = close.shift(1)
        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # EWM для ML (более гладкие features)
        alpha = 1.0 / period
        atr_series = tr.ewm(alpha=alpha, adjust=False, min_periods=1).mean()
        
        # ✅ ИСПРАВЛЕНО: Заменяем deprecated fillna(method='bfill')
        atr_series = atr_series.bfill().fillna(0.0)
        
        return atr_series.astype('float64')
        
    except Exception as e:
        logging.error(f"📊 ATR series for ML failed: {e}")
        # Возвращаем нулевой series той же длины
        return pd.Series([0.0] * len(df), index=df.index)

# =============================================================================
# ✅ UNIFIED CACHE FUNCTIONS - ЗАМЕНА СТАРОГО КЭША
# =============================================================================

def _create_cache_key(df: pd.DataFrame, params: str = "") -> str:
    """Создание ключа кэша для DataFrame"""
    try:
        if df.empty:
            return f"empty_{params}"
        
        # Используем последние 10 строк + размер + params для ключа
        tail_data = df.tail(10)[['close', 'volume', 'high', 'low']].values
        data_str = f"{len(df)}_{str(tail_data)}_{params}"
        return hashlib.md5(data_str.encode()).hexdigest()[:16]
    except Exception:
        return f"fallback_{len(df)}_{time.time()}_{params}"

def _get_cached_indicators(df: pd.DataFrame, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """Получение индикаторов из unified кэша"""
    if not use_cache or not CACHE_AVAILABLE:
        return None
    
    try:
        cache_key = _create_cache_key(df, "indicators")
        cached_result = cache_manager.get(cache_key, CacheNamespace.INDICATORS)
        
        if cached_result is not None:
            logging.debug(f"📊 Cache HIT for indicators: {cache_key[:8]}...")
            return cached_result
        else:
            logging.debug(f"📊 Cache MISS for indicators: {cache_key[:8]}...")
            return None
            
    except Exception as e:
        logging.error(f"📊 Cache get failed: {e}")
        return None

def _set_cached_indicators(df: pd.DataFrame, result: pd.DataFrame, use_cache: bool = True) -> bool:
    """Сохранение индикаторов в unified кэш"""
    if not use_cache or not CACHE_AVAILABLE:
        return False
    
    try:
        cache_key = _create_cache_key(df, "indicators")
        success = cache_manager.set(
            cache_key, 
            result.copy(), 
            CacheNamespace.INDICATORS,
            metadata={"rows": len(result), "cols": len(result.columns)}
        )
        
        if success:
            logging.debug(f"📊 Cache SET for indicators: {cache_key[:8]}...")
        
        return success
        
    except Exception as e:
        logging.error(f"📊 Cache set failed: {e}")
        return False

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
        self._ema_cache = {}  # Локальный кэш для EMA различных периодов
        
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
# ✅ ГЛАВНАЯ ФУНКЦИЯ С UNIFIED CACHE И UNIFIED ATR
# =============================================================================

def calculate_all_indicators(df: pd.DataFrame, use_cache: bool = True) -> pd.DataFrame:
    """
    ✅ UNIFIED VERSION: Расчёт индикаторов с UNIFIED CACHE и UNIFIED ATR
    
    Теперь использует:
    - Unified Cache Manager вместо _indicator_cache
    - get_unified_atr() вместо встроенного ATR расчета
    - Namespace INDICATORS для кэширования
    
    Features:
    - Централизованное кэширование через UnifiedCacheManager
    - ЕДИНЫЙ ATR расчет через get_unified_atr()
    - Переиспользование промежуточных вычислений
    - Оптимизированные алгоритмы
    - Graceful обработка ошибок
    
    Args:
        df: DataFrame с колонками open, high, low, close, volume
        use_cache: Использовать unified кэширование (по умолчанию True)
        
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

    # ✅ ПРОВЕРЯЕМ UNIFIED CACHE
    cached_result = _get_cached_indicators(df, use_cache)
    if cached_result is not None:
        calc_time = time.time() - start_time
        logging.debug(f"📊 Indicators from UNIFIED cache in {calc_time:.3f}s")
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

        # ✅ UNIFIED ATR - теперь используем единую функцию
        unified_atr_series = _atr_series_for_ml(out, period=14)
        out["atr"] = _safe_tail_fill(unified_atr_series)

        # ADX (используя UNIFIED ATR)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

        # Используем уже рассчитанный UNIFIED ATR
        atr = out["atr"]
        plus_di = 100.0 * (plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean() / (atr + _EPS))
        minus_di = 100.0 * (minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean() / (atr + _EPS))
        dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + _EPS)).astype("float64")
        adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=1).mean()
        
        out["adx"] = _safe_tail_fill(adx.astype("float64"))

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

        # ✅ СОХРАНЯЕМ В UNIFIED CACHE
        _set_cached_indicators(df, out, use_cache)

        calc_time = time.time() - start_time
        cache_status = "UNIFIED cached" if use_cache and CACHE_AVAILABLE else "not cached"
        logging.debug(f"📊 Indicators calculated in {calc_time:.3f}s, {cache_status}")
        
        return out

    except Exception as e:
        logging.exception(f"Technical indicators calculation failed: {e}")
        return df.copy()

# =============================================================================
# ✅ UNIFIED CACHE UTILITIES
# =============================================================================

def clear_indicator_cache():
    """✅ ОБНОВЛЕНО: Очистить unified кэш индикаторов"""
    if CACHE_AVAILABLE:
        cache_manager.clear_namespace(CacheNamespace.INDICATORS)
        logging.info("📊 Unified indicator cache cleared")
    else:
        logging.warning("📊 Unified cache not available")

def get_cache_stats() -> Dict[str, Any]:
    """✅ ОБНОВЛЕНО: Статистика unified кэша"""
    if CACHE_AVAILABLE:
        all_stats = cache_manager.get_stats()
        return {
            "indicators_namespace": all_stats["namespaces"].get("indicators", {}),
            "global_stats": all_stats["global"],
            "unified_cache": True
        }
    else:
        return {
            "unified_cache": False,
            "message": "Unified cache not available"
        }

def get_indicator_cache_top_keys(limit: int = 10) -> List[Dict[str, Any]]:
    """✅ НОВОЕ: Топ ключей кэша индикаторов"""
    if CACHE_AVAILABLE:
        return cache_manager.get_top_keys(CacheNamespace.INDICATORS, limit)
    else:
        return []

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

# =============================================================================
# UNIFIED ATR TESTING UTILITIES
# =============================================================================

def test_unified_atr_compatibility():
    """
    ✅ ТЕСТИРОВАНИЕ: Проверка совместимости unified ATR
    """
    try:
        # Создаем тестовые данные
        test_data = pd.DataFrame({
            'open': [100, 101, 102, 103, 104],
            'high': [102, 103, 104, 105, 106], 
            'low': [99, 100, 101, 102, 103],
            'close': [101, 102, 103, 104, 105],
            'volume': [1000, 1100, 1200, 1300, 1400]
        })
        
        # Тестируем все unified функции
        results = {}
        
        # Основная функция
        results['unified'] = get_unified_atr(test_data, period=3, method='ewm')
        results['unified_sma'] = get_unified_atr(test_data, period=3, method='sma')
        
        # Алиасы совместимости
        results['main_atr'] = atr(test_data, period=3)
        results['telegram_atr'] = _atr_for_telegram(test_data, period=3)
        results['risk_atr'] = _atr_for_risk_manager(test_data, period=3)
        results['ml_atr'] = _atr_series_for_ml(test_data, period=3).iloc[-1]
        
        # Проверяем что все функции возвращают разумные значения
        for name, value in results.items():
            print(f"📊 {name}: {value}")
            assert value is not None and value > 0, f"{name} returned invalid value: {value}"
        
        # Проверяем что EWM версии дают одинаковые результаты
        ewm_functions = ['unified', 'main_atr', 'telegram_atr']
        ewm_values = [results[func] for func in ewm_functions]
        
        # Допускаем небольшие различия из-за обработки ошибок
        assert all(abs(v - ewm_values[0]) < 0.01 for v in ewm_values), \
            f"EWM functions give different results: {ewm_values}"
        
        print("✅ All unified ATR functions work correctly!")
        return True
        
    except Exception as e:
        print(f"❌ Unified ATR test failed: {e}")
        return False

def test_unified_cache_integration():
    """✅ НОВОЕ: Тестирование интеграции unified cache"""
    if not CACHE_AVAILABLE:
        print("❌ Unified cache not available for testing")
        return False
    
    try:
        # Создаем тестовые данные
        test_data = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [102, 103, 104], 
            'low': [99, 100, 101],
            'close': [101, 102, 103],
            'volume': [1000, 1100, 1200]
        })
        
        # Очищаем кэш
        clear_indicator_cache()
        
        # Первый вызов - должен кэшироваться
        start_time = time.time()
        result1 = calculate_all_indicators(test_data, use_cache=True)
        time1 = time.time() - start_time
        
        # Второй вызов - должен быть из кэша
        start_time = time.time()
        result2 = calculate_all_indicators(test_data, use_cache=True)
        time2 = time.time() - start_time
        
        # Проверяем результаты
        assert result1.equals(result2), "Cached result differs from original"
        assert time2 < time1 * 0.5, f"Cache didn't speed up calculation: {time1:.3f}s vs {time2:.3f}s"
        
        # Проверяем статистику
        stats = get_cache_stats()
        assert stats["unified_cache"], "Unified cache should be available"
        assert stats["indicators_namespace"]["entries"] > 0, "Cache should have entries"
        
        print("✅ Unified cache integration works correctly!")
        print(f"📊 Performance: {time1:.3f}s -> {time2:.3f}s ({time2/time1*100:.1f}%)")
        return True
        
    except Exception as e:
        print(f"❌ Unified cache test failed: {e}")
        return False

# Экспорт для обратной совместимости
__all__ = [
    # ✅ НОВЫЕ UNIFIED ФУНКЦИИ
    'get_unified_atr',           # Главная unified функция
    'atr',                       # Алиас для main.py
    '_atr_for_telegram',         # Алиас для bot_handler.py  
    '_atr_for_risk_manager',     # Алиас для risk_manager.py
    '_atr_series_for_ml',        # Для ML модели
    
    # Существующие функции (обновлены для unified cache)
    'calculate_all_indicators',
    'clear_indicator_cache', 
    'get_cache_stats',
    'get_last_indicator_value',
    
    # ✅ НОВЫЕ UNIFIED CACHE ФУНКЦИИ
    'get_indicator_cache_top_keys',
    
    # Тестирование
    'test_unified_atr_compatibility',
    'test_unified_cache_integration'
]