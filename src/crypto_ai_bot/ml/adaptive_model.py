# ml/adaptive_model.py

from __future__ import annotations

import os
import logging
from typing import Dict, Optional, Tuple, List, Union, Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight

from config.settings import MarketCondition
class MLModelException(Exception):
    """РћС€РёР±РєРё ML РјРѕРґРµР»Рё"""
    pass


_EPS = 1e-12
# РџСЂРёРѕСЂРёС‚РµС‚: MODEL_DIR > MODELS_DIR > "models"
DEFAULT_MODELS_DIR = (
    os.getenv("MODEL_DIR")
    or os.getenv("MODELS_DIR")
    or "models"
)


def _clip01(x: float) -> float:
    try:
        v = float(x)
        if not np.isfinite(v):
            return 0.5
        return float(min(1.0, max(0.0, v)))
    except Exception:
        return 0.5


class AdaptiveMLModel:
    """
    вњ… Р­РўРђРџ 5: UNIFIED ATR РРќРўР•Р“Р РђР¦РРЇ
    РђРґР°РїС‚РёРІРЅР°СЏ ML РјРѕРґРµР»СЊ СЃ unified ATR СЃРёСЃС‚РµРјРѕР№:
      - РїРѕРґРјРѕРґРµР»Рё РїРѕРґ СЂС‹РЅРѕС‡РЅС‹Рµ СѓСЃР»РѕРІРёСЏ + GLOBAL
      - РёР·РІР»РµС‡РµРЅРёРµ С„РёС‡ РёР· df OHLCV
      - predict(...) РїСЂРёРЅРёРјР°РµС‚ РєР°Рє ndarray, С‚Р°Рє Рё dict С„РёС‡ (СЃРѕРІРјРµСЃС‚РёРјРѕ СЃ main.py)
      - UNIFIED ATR РІРѕ РІСЃРµС… СЂР°СЃС‡РµС‚Р°С…
    """

    def __init__(self, models_dir: Optional[str] = None, *, model_dir: Optional[str] = None):
        """
        РЎРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ РїР°СЂР°РјРµС‚СЂРѕРІ:
          - models_dir (РѕСЃРЅРѕРІРЅРѕР№)
          - model_dir (Р°Р»РёР°СЃ)
        Р•СЃР»Рё РЅРµ Р·Р°РґР°РЅРѕ вЂ” Р±РµСЂС‘Рј РёР· env (MODEL_DIR / MODELS_DIR) РёР»Рё "models".
        """
        self.models_dir: str = models_dir or model_dir or DEFAULT_MODELS_DIR
        self.models: Dict[str, RandomForestClassifier] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.feature_importance: Dict[str, Optional[np.ndarray]] = {}
        self.is_trained: bool = False

        self.conditions: List[str] = [
            MarketCondition.STRONG_BULL.value,
            MarketCondition.WEAK_BULL.value,
            MarketCondition.SIDEWAYS.value,
            MarketCondition.WEAK_BEAR.value,
            MarketCondition.STRONG_BEAR.value,
            "GLOBAL",
        ]

        # РїРѕРїС‹С‚РєР° Р·Р°РіСЂСѓР·РёС‚СЊ СЃРѕС…СЂР°РЅС‘РЅРЅС‹Рµ РјРѕРґРµР»Рё
        try:
            self.load_models()
        except Exception:
            logging.exception("load_models at init failed")

    # -------------------------------------------------------------------------
    # TRAIN
    # -------------------------------------------------------------------------
    def train(self, X: np.ndarray, y: np.ndarray, market_conditions: List[str]) -> bool:
        try:
            if X is None or y is None or len(X) == 0 or len(y) == 0:
                raise MLModelException("Empty training data")

            X = np.asarray(X, dtype=np.float64)
            y = np.asarray(y, dtype=np.int32)

            # GLOBAL РјРѕРґРµР»СЊ (РІСЃРµРіРґР° РїСЂРѕР±СѓРµРј РѕР±СѓС‡РёС‚СЊ)
            ok_global = self._fit_one("GLOBAL", X, y)

            # РњРѕРґРµР»Рё РїРѕ СѓСЃР»РѕРІРёСЏРј СЂС‹РЅРєР°
            uniq = sorted(set(market_conditions))
            any_ok = ok_global
            for cond in uniq:
                mask = (np.asarray(market_conditions) == cond)
                X_c = X[mask]
                y_c = y[mask]
                if len(X_c) < 40 or len(np.unique(y_c)) < 2:
                    logging.warning(f"Not enough data for condition={cond}: {len(X_c)} samples or single class")
                    continue
                ok = self._fit_one(cond, X_c, y_c)
                any_ok = any_ok or ok

            self.is_trained = any_ok
            if any_ok:
                self.save_models()
            return self.is_trained

        except Exception as e:
            logging.exception(f"Model training failed: {e}")
            return False

    def _fit_one(self, key: str, X: np.ndarray, y: np.ndarray) -> bool:
        """РћР±СѓС‡РµРЅРёРµ РѕРґРЅРѕР№ РјРѕРґРµР»Рё СЃ РјР°СЃС€С‚Р°Р±РёСЂРѕРІР°РЅРёРµРј Рё class_weight."""
        try:
            classes = np.array([0, 1], dtype=np.int32)
            try:
                weights = compute_class_weight(class_weight="balanced", classes=classes, y=y)
                cw = {int(c): float(w) for c, w in zip(classes, weights)}
            except Exception:
                cw = "balanced"

            scaler = StandardScaler()
            Xs = scaler.fit_transform(X)

            model = RandomForestClassifier(
                n_estimators=300,
                max_depth=None,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1,
                class_weight=cw,
            )
            model.fit(Xs, y)

            self.models[key] = model
            self.scalers[key] = scaler
            try:
                self.feature_importance[key] = getattr(model, "feature_importances_", None)
            except Exception:
                self.feature_importance[key] = None

            logging.info(f"вњ… Trained model [{key}] on {len(X)} samples")
            return True
        except Exception as e:
            logging.error(f"Fit failed for {key}: {e}")
            return False

    # -------------------------------------------------------------------------
    # PREDICT (СЃРѕРІРјРµСЃС‚РёРј СЃ main.py)
    # -------------------------------------------------------------------------
    def _vec_from_features_dict(self, feats: Dict[str, Any]) -> np.ndarray:
        """
        РџСЂРёРІРѕРґРёРј dict (РєР°Рє РІ main.py) Рє РІРµРєС‚РѕСЂСѓ, РєРѕС‚РѕСЂС‹Р№ РѕР¶РёРґР°РµС‚ РјРѕРґРµР»СЊ:
          [rsi, macd, ema_cross, bb_pos, stoch_k, adx, volume_ratio, price_change]
        Р§Р°СЃС‚Рё, РєРѕС‚РѕСЂС‹С… РЅРµС‚ РІ dict, Р·Р°РїРѕР»РЅСЏРµРј СЂР°Р·СѓРјРЅС‹РјРё С„РѕР»Р±СЌРєР°РјРё.
        """
        # 1) RSI
        rsi = float(feats.get("rsi", 50.0) or 50.0)

        # 2) MACD (Р±РµСЂС‘Рј macd_line, Р° РЅРµ hist/signal)
        macd = float(feats.get("macd", 0.0) or 0.0)

        # 3) EMA cross РёР· ema_20 Рё ema_50
        ema_20 = feats.get("ema_20", None)
        ema_50 = feats.get("ema_50", None)
        if ema_20 is not None and ema_50 is not None and float(ema_50) != 0:
            ema_cross = (float(ema_20) - float(ema_50)) / (abs(float(ema_50)) + _EPS)
        else:
            ema_cross = 0.0

        # 4) bb_pos вЂ” РЅРµС‚ РІ dict в†’ РЅРµР№С‚СЂР°Р»СЊРЅР°СЏ СЃРµСЂРµРґРёРЅР°
        bb_pos = 0.5

        # 5) stoch_k вЂ” РЅРµС‚ РІ dict в†’ СЃСЂРµРґРЅРµРµ
        stoch_k = 50.0

        # 6) adx вЂ” РЅРµС‚ РІ dict в†’ СѓРјРµСЂРµРЅРЅРѕРµ С‚СЂРµРЅРґРѕРІРѕРµ 20
        adx = 20.0

        # 7) volume_ratio вЂ” РѕС†РµРЅРёРј С‡РµСЂРµР· vol_change (1 + О”, РѕС‚СЃРµС‡С‘Рј РЅРёР¶Рµ 0.1)
        vc = feats.get("vol_change", 0.0)
        try:
            volume_ratio = float(1.0 + float(vc))
        except Exception:
            volume_ratio = 1.0
        volume_ratio = float(np.clip(volume_ratio, 0.1, 5.0))

        # 8) price_change вЂ” РІРѕР·СЊРјС‘Рј 5-Р±Р°СЂРЅС‹Р№, РµСЃР»Рё РµСЃС‚СЊ, РёРЅР°С‡Рµ 1-Р±Р°СЂРЅС‹Р№
        pc5 = feats.get("price_change_5", None)
        pc1 = feats.get("price_change_1", 0.0)
        try:
            price_change = float(pc5 if pc5 is not None else pc1)
        except Exception:
            price_change = 0.0

        vec = np.array([
            float(rsi),
            float(macd),
            float(ema_cross),
            float(bb_pos),
            float(stoch_k),
            float(adx),
            float(volume_ratio),
            float(price_change),
        ], dtype=np.float64)

        vec[~np.isfinite(vec)] = 0.0
        return vec

    def predict(
        self,
        x_vec: Union[np.ndarray, Dict[str, Any]],
        market_condition: Optional[str] = None
    ) -> Tuple[float, float]:
        """
        вњ… РРЎРџР РђР’Р›Р•РќРћ: РџСЂРёРЅРёРјР°РµС‚ Р»РёР±Рѕ ndarray, Р»РёР±Рѕ dict С„РёС‡ (СЃРѕРІРјРµСЃС‚РёРјРѕ СЃ main.py).
        Р’РѕР·РІСЂР°С‰Р°РµС‚ (pred, confidence) РіРґРµ confidence в€€ [0..1].
        """
        try:
            if isinstance(x_vec, dict):
                x = self._vec_from_features_dict(x_vec).reshape(1, -1)
                logging.debug(f"рџ¤– Converted dict features to vector: shape={x.shape}")
            else:
                x = np.asarray(x_vec, dtype=np.float64).reshape(1, -1)
                logging.debug(f"рџ¤– Using provided vector: shape={x.shape}")

            # СЃРЅР°С‡Р°Р»Р° СѓСЃР»РѕРІРЅР°СЏ РјРѕРґРµР»СЊ, РµСЃР»Рё РµСЃС‚СЊ
            if market_condition and market_condition in self.models:
                prob = self._predict_proba_with("cond", market_condition, x)
                if prob is not None:
                    result = (1.0 if prob >= 0.5 else 0.0), float(prob)
                    logging.debug(f"рџ¤– AI predict [cond:{market_condition}]: {result}")
                    return result

            # Р·Р°С‚РµРј GLOBAL
            if "GLOBAL" in self.models:
                prob = self._predict_proba_with("global", "GLOBAL", x)
                if prob is not None:
                    result = (1.0 if prob >= 0.5 else 0.0), float(prob)
                    logging.debug(f"рџ¤– AI predict [GLOBAL]: {result}")
                    return result

            # С„РѕР»Р±СЌРє
            pred, conf = self._fallback_prediction(x.reshape(-1))
            logging.debug(f"рџ¤– AI predict [fallback]: ({pred}, {conf})")
            return pred, conf

        except Exception as e:
            logging.error(f"Prediction failed: {e}")
            fallback_result = self._fallback_prediction(
                self._vec_from_features_dict(x_vec) if isinstance(x_vec, dict) else np.asarray(x_vec, dtype=np.float64)
            )
            logging.debug(f"рџ¤– AI predict [error_fallback]: {fallback_result}")
            return fallback_result

    def _predict_proba_with(self, tag: str, key: str, x: np.ndarray) -> Optional[float]:
        try:
            scaler = self.scalers[key]
            model = self.models[key]
            xs = scaler.transform(x)
            proba = model.predict_proba(xs)[0, 1]
            proba = float(np.clip(proba, 0.0, 1.0))
            logging.debug(f"рџ¤– predict_proba[{tag}:{key}] в†’ {proba:.3f}")
            return proba
        except Exception as e:
            logging.error(f"predict_proba[{tag}:{key}] failed: {e}")
            return None

    # High-level API (РїРѕРґРґРµСЂР¶РєР° df)
    def predict_proba(self, df_tail_15m: pd.DataFrame, fallback_when_short=True) -> float:
        """вњ… РРЎРџР РђР’Р›Р•РќРћ: Р”РѕР±Р°РІР»РµРЅРѕ Р»РѕРіРёСЂРѕРІР°РЅРёРµ РґР»СЏ РѕС‚Р»Р°РґРєРё"""
        try:
            logging.debug(f"рџ¤– predict_proba called with df shape: {df_tail_15m.shape}")
            x = self._features_from_df(df_tail_15m)
            if x is None:
                logging.debug("рџ¤– Features extraction failed, returning fallback")
                return 0.55 if fallback_when_short else 0.50

            cond = self._infer_condition_from_df(df_tail_15m)
            logging.debug(f"рџ¤– Inferred market condition: {cond}")
            
            _pred, prob = self.predict(x, cond)
            result = _clip01(prob)
            logging.debug(f"рџ¤– predict_proba result: {result}")
            return result
        except Exception:
            logging.exception("predict_proba failed")
            return 0.55 if fallback_when_short else 0.50

    # -------------------------------------------------------------------------
    # MODEL IO
    # -------------------------------------------------------------------------
    def save_models(self, dirpath: Optional[str] = None):
        try:
            dirpath = dirpath or self.models_dir or DEFAULT_MODELS_DIR
            os.makedirs(dirpath, exist_ok=True)
            for k, m in self.models.items():
                joblib.dump(m, os.path.join(dirpath, f"model_{k}.pkl"))
                sc = self.scalers.get(k)
                if sc is not None:
                    joblib.dump(sc, os.path.join(dirpath, f"scaler_{k}.pkl"))
            logging.info(f"вњ… Models saved to {dirpath}")
        except Exception as e:
            logging.error(f"Failed to save models: {e}")

    def load_models(self, dirpath: Optional[str] = None) -> bool:
        try:
            dirpath = dirpath or self.models_dir or DEFAULT_MODELS_DIR
            loaded = 0
            for k in self.conditions:
                mp = os.path.join(dirpath, f"model_{k}.pkl")
                sp = os.path.join(dirpath, f"scaler_{k}.pkl")
                if os.path.exists(mp) and os.path.exists(sp):
                    self.models[k] = joblib.load(mp)
                    self.scalers[k] = joblib.load(sp)
                    loaded += 1
            self.is_trained = loaded > 0
            logging.info(f"вњ… Loaded {loaded} models from {dirpath}")
            return self.is_trained
        except Exception as e:
            logging.error(f"Failed to load models: {e}")
            return False

    # -------------------------------------------------------------------------
    # FALLBACK СЌРІСЂРёСЃС‚РёРєР°
    # -------------------------------------------------------------------------
    def _fallback_prediction(self, x_vec: np.ndarray) -> Tuple[float, float]:
        try:
            x = np.asarray(x_vec, dtype=np.float64)
            # РѕР¶РёРґР°РµРј РІРµРєС‚РѕСЂ РґР»РёРЅС‹ 8, РєР°Рє РІ _features_from_df/_vec_from_features_dict
            # РµСЃР»Рё РґР»РёРЅР° РёРЅР°СЏ вЂ” Р±РµР·РѕРїР°СЃРЅРѕ РѕР±СЂРµР¶РµРј/РґРѕРїРѕР»РЅСЏРµРј РЅСѓР»СЏРјРё
            if x.size != 8:
                x = np.pad(x[:8], (0, max(0, 8 - x.size)), constant_values=0.0)

            score = 0.0
            if 30 <= x[0] <= 70:      # rsi
                score += 0.2
            if x[1] > 0:              # macd
                score += 0.25
            if x[2] > 0:              # ema_cross
                score += 0.2
            if 0.2 <= x[3] <= 0.8:    # bb_pos
                score += 0.1
            if x[4] >= 50:            # stoch_k
                score += 0.1
            if x[5] >= 18:            # adx
                score += 0.05
            if x[6] > 1.0:            # volume_ratio
                score += 0.05
            if x[7] > 0:              # price_change
                score += 0.05

            pred = 1.0 if score >= 0.5 else 0.0
            conf = score if pred == 1.0 else (1.0 - score)
            return float(pred), float(_clip01(conf))
        except Exception:
            return 0.0, 0.5

    # -------------------------------------------------------------------------
    # вњ… Р­РўРђРџ 5: FEATURE ENGINEERING РЎ UNIFIED ATR
    # -------------------------------------------------------------------------
    def _features_from_df(self, df: pd.DataFrame) -> Optional[np.ndarray]:
        """вњ… Р­РўРђРџ 5: РЎС‚СЂРѕРёРј 8-С„РёС‡ РІРµРєС‚РѕСЂ РёР· df СЃ UNIFIED ATR."""
        if df is None or df.empty or not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None

        d = df.copy()
        close = d["close"].astype("float64")
        high = d["high"].astype("float64")
        low = d["low"].astype("float64")
        vol = d["volume"].astype("float64")

        # RSI(14)
        rsi = self._rsi(close, 14)

        # EMA 9/21 + cross
        ema9 = close.ewm(span=9, adjust=False, min_periods=5).mean()
        ema21 = close.ewm(span=21, adjust=False, min_periods=5).mean()
        ema_cross = (ema9.iloc[-1] - ema21.iloc[-1]) / (abs(ema21.iloc[-1]) + _EPS) if len(ema21.dropna()) else 0.0

        # MACD (12,26) вЂ” Р±РµСЂС‘Рј macd (Р±РµР· СЃРёРіРЅР°Р»СЊРЅРѕР№)
        ema_fast = close.ewm(span=12, adjust=False, min_periods=5).mean()
        ema_slow = close.ewm(span=26, adjust=False, min_periods=5).mean()
        macd = float((ema_fast.iloc[-1] - ema_slow.iloc[-1])) if len(ema_slow.dropna()) else 0.0

        # Bollinger(20,2) в†’ РїРѕР·РёС†РёСЏ РІ РґРёР°РїР°Р·РѕРЅРµ
        mid = close.rolling(window=20, min_periods=5).mean()
        std = close.rolling(window=20, min_periods=5).std(ddof=0)
        upper = mid + 2.0 * (std.fillna(0.0))
        lower = mid - 2.0 * (std.fillna(0.0))
        rng = (upper.iloc[-1] - lower.iloc[-1])
        bb_pos = float((close.iloc[-1] - lower.iloc[-1]) / (rng + _EPS)) if np.isfinite(rng) else 0.5
        bb_pos = float(np.clip(bb_pos, 0.0, 1.0))

        # Stoch(14) K
        ll = low.rolling(window=14, min_periods=5).min()
        hh = high.rolling(window=14, min_periods=5).max()
        denom = (hh.iloc[-1] - ll.iloc[-1])
        stoch_k = float((close.iloc[-1] - ll.iloc[-1]) / (denom + _EPS) * 100.0) if np.isfinite(denom) else 50.0
        stoch_k = float(np.clip(stoch_k, 0.0, 100.0))

        # вњ… Р­РўРђРџ 5: ADX РЎ UNIFIED ATR
        adx = self._adx_with_unified_atr(high, low, close, 14)

        # Volume ratio(20)
        vma = vol.rolling(window=20, min_periods=5).mean()
        volume_ratio = float(vol.iloc[-1] / (vma.iloc[-1] + _EPS)) if len(vma.dropna()) else 1.0

        # Price change (10 Р±Р°СЂРѕРІ)
        look = min(10, max(1, len(close) - 1))
        price_change = float((close.iloc[-1] - close.iloc[-look]) / (abs(close.iloc[-look]) + _EPS))

        feats = np.array([
            float(rsi), float(macd), float(ema_cross), float(bb_pos),
            float(stoch_k), float(adx), float(volume_ratio), float(price_change)
        ], dtype=np.float64)

        feats[~np.isfinite(feats)] = 0.0
        return feats

    def _rsi(self, close: pd.Series, period: int = 14) -> float:
        if len(close) < period + 2:
            return 50.0
        delta = close.diff()
        up = delta.clip(lower=0.0)
        down = -delta.clip(upper=0.0)
        roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
        roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
        rs = roll_up / (roll_down + _EPS)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        val = float(rsi.iloc[-1])
        return float(val) if np.isfinite(val) else 50.0

    def _adx_with_unified_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        """вњ… Р­РўРђРџ 5: ADX СЃ UNIFIED ATR СЃРёСЃС‚РµРјРѕР№"""
        if len(close) < period + 2:
            return 20.0
            
        try:
            up_move = high.diff()
            down_move = -low.diff()
            plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
            minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

            # вњ… UNIFIED ATR РРќРўР•Р“Р РђР¦РРЇ
            try:
                from crypto_ai_bot.core.indicators.unified import _atr_series_for_ml
                temp_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
                atr = _atr_series_for_ml(temp_df, period)
                logging.debug(f"рџ¤– ML Model: Using UNIFIED ATR for ADX calculation")
            except Exception as e:
                logging.warning(f"рџ¤– ML Model: UNIFIED ATR failed, using fallback: {e}")
                # Fallback Рє РїСЂСЏРјРѕРјСѓ СЂР°СЃС‡РµС‚Сѓ
                prev_close = close.shift(1)
                tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                atr = tr.ewm(alpha=1 / period, adjust=False).mean()

            plus_di = 100.0 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + _EPS))
            minus_di = 100.0 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + _EPS))
            dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + _EPS))
            adx = dx.ewm(alpha=1 / period, adjust=False).mean()
            
            val = float(adx.iloc[-1])
            return float(val) if np.isfinite(val) else 20.0
            
        except Exception as e:
            logging.error(f"рџ¤– ML Model: ADX calculation failed: {e}")
            return 20.0

    def _infer_condition_from_df(self, df: pd.DataFrame) -> str:
        try:
            close = df["close"].astype("float64")
            ema_fast = close.ewm(span=20, adjust=False, min_periods=5).mean()
            ema_slow = close.ewm(span=50, adjust=False, min_periods=5).mean()

            ema_gap = float((ema_fast.iloc[-1] - ema_slow.iloc[-1]) / (abs(ema_slow.iloc[-1]) + _EPS))
            rsi = self._rsi(close, 14)

            strong_gap = 0.004  # ~0.4%

            if ema_gap > strong_gap and rsi >= 55:
                return MarketCondition.STRONG_BULL.value
            if ema_gap > 0 and rsi >= 50:
                return MarketCondition.WEAK_BULL.value
            if ema_gap < -strong_gap and rsi <= 45:
                return MarketCondition.STRONG_BEAR.value
            if ema_gap < 0 and rsi <= 50:
                return MarketCondition.WEAK_BEAR.value
            return MarketCondition.SIDEWAYS.value
        except Exception:
            return MarketCondition.SIDEWAYS.value



