import numpy as np
import pandas as pd
import joblib
import logging
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from typing import Tuple, Optional
from config.settings import MarketCondition
from core.exceptions import MLModelException

class AdaptiveMLModel:
    """Адаптивная ML модель для разных рыночных условий"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.feature_importance = {}
        self.is_trained = False
    
    def train(self, X: np.ndarray, y: np.ndarray, market_conditions: list) -> bool:
        """Обучение моделей для разных рыночных условий"""
        try:
            unique_conditions = list(set(market_conditions))
            
            for condition in unique_conditions:
                # Фильтрация данных по условию
                condition_mask = np.array(market_conditions) == condition
                X_condition = X[condition_mask]
                y_condition = y[condition_mask]
                
                if len(X_condition) < 10:  # Минимум данных для обучения
                    logging.warning(f"Not enough data for {condition}: {len(X_condition)} samples")
                    continue
                
                # Масштабирование
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X_condition)
                
                # Обучение модели
                model = RandomForestClassifier(
                    n_estimators=100,
                    max_depth=10,
                    random_state=42,
                    n_jobs=-1
                )
                model.fit(X_scaled, y_condition)
                
                # Сохранение
                self.models[condition] = model
                self.scalers[condition] = scaler
                self.feature_importance[condition] = model.feature_importances_
                
                logging.info(f"✅ Model trained for {condition}: {len(X_condition)} samples")
            
            self.is_trained = len(self.models) > 0
            return self.is_trained
            
        except Exception as e:
            logging.error(f"Model training failed: {e}")
            return False
    
    def predict(self, X: np.ndarray, market_condition: str) -> Tuple[float, float]:
        """Предсказание для конкретного рыночного условия"""
        try:
            if not self.is_trained or market_condition not in self.models:
                # Fallback на общую модель
                return self._fallback_prediction(X)
            
            model = self.models[market_condition]
            scaler = self.scalers[market_condition]
            
            # Масштабирование
            X_scaled = scaler.transform(X.reshape(1, -1))
            
            # Предсказание
            probability = model.predict_proba(X_scaled)[0]
            prediction = model.predict(X_scaled)[0]
            confidence = np.max(probability)
            
            return float(prediction), float(confidence)
            
        except Exception as e:
            logging.error(f"Prediction failed: {e}")
            return self._fallback_prediction(X)
    
    def _fallback_prediction(self, X: np.ndarray) -> Tuple[float, float]:
        """Простая fallback логика"""
        try:
            # Простая логика на основе технических индикаторов
            # X должен содержать: [RSI, MACD, EMA_cross, BB_position, Stoch, ADX, Volume_ratio, Price_change]
            
            score = 0.0
            
            # RSI
            if 30 <= X[0] <= 70:
                score += 0.2
            
            # MACD
            if X[1] > 0:
                score += 0.3
            
            # EMA cross
            if X[2] > 0:
                score += 0.2
            
            # Bollinger position
            if 0.2 <= X[3] <= 0.8:
                score += 0.1
            
            # Volume
            if X[6] > 1.0:
                score += 0.2
            
            prediction = 1.0 if score > 0.5 else 0.0
            confidence = score if score > 0.5 else (1.0 - score)
            
            return prediction, confidence
            
        except:
            return 0.0, 0.5
    
    def save_models(self, filepath: str = "models/"):
        """Сохранение обученных моделей"""
        try:
            # Создание директории если не существует
            os.makedirs(filepath, exist_ok=True)
            
            for condition, model in self.models.items():
                model_path = f"{filepath}model_{condition}.pkl"
                scaler_path = f"{filepath}scaler_{condition}.pkl"
                
                joblib.dump(model, model_path)
                joblib.dump(self.scalers[condition], scaler_path)
            
            logging.info("✅ Models saved successfully")
            
        except Exception as e:
            logging.error(f"Failed to save models: {e}")
    
    def load_models(self, filepath: str = "models/") -> bool:
        """Загрузка сохраненных моделей"""
        try:
            conditions = [MarketCondition.STRONG_BULL.value, MarketCondition.WEAK_BULL.value,
                         MarketCondition.SIDEWAYS.value, MarketCondition.WEAK_BEAR.value,
                         MarketCondition.STRONG_BEAR.value]
            
            for condition in conditions:
                model_path = f"{filepath}model_{condition}.pkl"
                scaler_path = f"{filepath}scaler_{condition}.pkl"
                
                if os.path.exists(model_path) and os.path.exists(scaler_path):
                    self.models[condition] = joblib.load(model_path)
                    self.scalers[condition] = joblib.load(scaler_path)
            
            self.is_trained = len(self.models) > 0
            logging.info(f"✅ Loaded {len(self.models)} models")
            return self.is_trained
            
        except Exception as e:
            logging.error(f"Failed to load models: {e}")
            return False