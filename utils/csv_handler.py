import pandas as pd
import numpy as np
import logging
import os
from typing import Optional
from core.exceptions import DataValidationException

class CSVHandler:
    """Безопасная работа с CSV файлами"""
    
    @staticmethod
    def read_csv_safe(filepath: str, expected_columns: list = None) -> Optional[pd.DataFrame]:
        """Безопасное чтение CSV с валидацией"""
        try:
            # Попытка прочитать с разными параметрами
            read_params = [
                {"sep": ",", "encoding": "utf-8"},
                {"sep": ",", "encoding": "cp1251"},
                {"sep": ",", "encoding": "windows-1251"},
                {"sep": ",", "encoding": "latin-1"},
                {"sep": ";", "encoding": "utf-8"},
                {"sep": "\t", "encoding": "utf-8"}
            ]
            
            df = None
            for params in read_params:
                try:
                    df = pd.read_csv(filepath, **params, on_bad_lines='skip')
                    if len(df.columns) >= 3:  # Минимальное количество колонок
                        break
                except:
                    continue
            
            if df is None or df.empty:
                raise DataValidationException("Could not read CSV file")
            
            # Валидация структуры
            df = CSVHandler._validate_and_clean(df, expected_columns)
            
            logging.info(f"✅ CSV loaded: {len(df)} rows, {len(df.columns)} columns")
            return df
            
        except Exception as e:
            logging.error(f"Failed to read CSV {filepath}: {e}")
            return None
    
    @staticmethod
    def _validate_and_clean(df: pd.DataFrame, expected_columns: list = None) -> pd.DataFrame:
        """Валидация и очистка данных"""
        try:
            # Удаление полностью пустых строк
            df = df.dropna(how='all')
            
            # Удаление дублирующихся строк
            df = df.drop_duplicates()
            
            # Проверка ожидаемых колонок
            if expected_columns:
                missing_cols = set(expected_columns) - set(df.columns)
                if missing_cols:
                    logging.warning(f"Missing columns: {missing_cols}")
            
            # Удаление строк с критическими пропусками
            if 'timestamp' in df.columns:
                df = df.dropna(subset=['timestamp'])
            
            # Конвертация типов данных
            for col in df.columns:
                if col in ['open', 'high', 'low', 'close', 'volume', 'price', 'rsi', 'macd', 'macd_signal', 'macd_histogram', 'total_score', 'ai_score', 'confidence']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                elif col == 'timestamp' or col == 'datetime':
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                elif col == 'main_reason':
                    # Очистка русского текста с проблемами кодировки
                    df[col] = df[col].astype(str).replace({'?': '', 'nan': 'Unknown'}, regex=True)
            
            # Удаление строк с NaN в критических колонках
            critical_cols = ['open', 'high', 'low', 'close'] if 'close' in df.columns else []
            if critical_cols:
                df = df.dropna(subset=critical_cols)
            
            return df.reset_index(drop=True)
            
        except Exception as e:
            logging.error(f"Data validation failed: {e}")
            raise DataValidationException(f"Data validation failed: {e}")
    
    @staticmethod
    def save_csv_safe(df: pd.DataFrame, filepath: str) -> bool:
        """Безопасное сохранение CSV"""
        try:
            df.to_csv(filepath, index=False, encoding='utf-8')
            logging.info(f"✅ CSV saved: {filepath}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to save CSV {filepath}: {e}")
            return False
    
    @staticmethod
    def append_to_csv(new_data: dict, filepath: str) -> bool:
        """Добавление новой строки в CSV"""
        try:
            # Проверяем существует ли файл
            if os.path.exists(filepath):
                df = CSVHandler.read_csv_safe(filepath)
                if df is not None:
                    # Добавляем новую строку
                    new_row = pd.DataFrame([new_data])
                    df = pd.concat([df, new_row], ignore_index=True)
                else:
                    df = pd.DataFrame([new_data])
            else:
                df = pd.DataFrame([new_data])
            
            return CSVHandler.save_csv_safe(df, filepath)
            
        except Exception as e:
            logging.error(f"Failed to append to CSV {filepath}: {e}")
            return False