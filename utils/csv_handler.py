# utils/csv_handler.py - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ С БАТЧИНГОМ

import csv
import os
import logging
import pandas as pd
import threading
import time
from datetime import datetime
from typing import List, Dict, Any, NamedTuple
from collections import deque
from config.settings import CLOSED_TRADES_CSV, SIGNALS_CSV, LOGS_DIR

# =============================================================================
# СИСТЕМА БАТЧИНГА CSV ЗАПИСЕЙ
# =============================================================================

class CSVRecord(NamedTuple):
    """Запись для батчинга"""
    file_path: str
    fieldnames: List[str] 
    data: Dict[str, Any]

class BatchCSVWriter:
    """Батчированная запись в CSV файлы"""
    
    def __init__(self, batch_size: int = 10, flush_interval: float = 30.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer = deque()
        self._lock = threading.RLock()
        self._last_flush = time.time()
        self._total_records = 0
        self._flush_count = 0
        
        # Запускаем фоновый флушер
        self._start_background_flusher()
        
    def add_record(self, file_path: str, fieldnames: List[str], data: Dict[str, Any]):
        """Добавить запись в буфер"""
        with self._lock:
            self._buffer.append(CSVRecord(file_path, fieldnames, data))
            self._total_records += 1
            
            # Немедленный flush при превышении размера батча
            if len(self._buffer) >= self.batch_size:
                self._flush_buffer()
    
    def _start_background_flusher(self):
        """Запустить фоновый процесс сброса буфера"""
        def background_flush():
            while True:
                time.sleep(self.flush_interval)
                with self._lock:
                    if self._buffer and time.time() - self._last_flush > self.flush_interval:
                        self._flush_buffer()
        
        thread = threading.Thread(target=background_flush, daemon=True, name="CSVBatchFlusher")
        thread.start()
        logging.debug("📄 Background CSV flusher started")
    
    def _flush_buffer(self):
        """Сбросить буфер в файлы"""
        if not self._buffer:
            return
            
        # Группируем записи по файлам для эффективности
        by_file = {}
        buffer_size = len(self._buffer)
        
        while self._buffer:
            record = self._buffer.popleft()
            if record.file_path not in by_file:
                by_file[record.file_path] = {
                    'fieldnames': record.fieldnames,
                    'records': []
                }
            by_file[record.file_path]['records'].append(record.data)
        
        # Записываем батчами по файлам
        for file_path, file_data in by_file.items():
            try:
                self._write_batch_to_file(file_path, file_data['fieldnames'], file_data['records'])
            except Exception as e:
                logging.error(f"Batch CSV write failed for {file_path}: {e}")
        
        self._last_flush = time.time()
        self._flush_count += 1
        
        logging.debug(f"📄 CSV batch flushed: {buffer_size} records to {len(by_file)} files")
    
    def _write_batch_to_file(self, file_path: str, fieldnames: List[str], records: List[Dict[str, Any]]):
        """Записать батч записей в один файл"""
        if not records:
            return
            
        # Создаем директорию и файл если нужно
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        
        file_exists = os.path.isfile(file_path)
        
        # Создаем заголовки если файл новый
        if not file_exists:
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
        
        # Добавляем все записи одним блоком
        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            for record_data in records:
                # Фильтруем данные по полям и заполняем пустые
                filtered_data = {}
                for field in fieldnames:
                    value = record_data.get(field, "")
                    # Конвертируем в строку для CSV
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        filtered_data[field] = str(value) if pd.notna(value) else ""
                    else:
                        filtered_data[field] = str(value) if value is not None else ""
                        
                writer.writerow(filtered_data)
    
    def force_flush(self):
        """Принудительно сбросить буфер"""
        with self._lock:
            self._flush_buffer()
    
    def get_stats(self) -> Dict[str, Any]:
        """Статистика батчера"""
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "total_records": self._total_records,
                "flush_count": self._flush_count,
                "last_flush": self._last_flush,
                "batch_size": self.batch_size,
                "flush_interval": self.flush_interval
            }

# Глобальный батчер
_csv_batcher = BatchCSVWriter(batch_size=15, flush_interval=20.0)

# =============================================================================
# ОПТИМИЗИРОВАННЫЙ CSV HANDLER
# =============================================================================

class CSVHandler:
    """Оптимизированный обработчик CSV с батчингом и кэшированием"""
    
    # Упрощенные поля для сигналов
    SIGNALS_FIELDS = [
        "timestamp", "symbol", "timeframe", "close", 
        "buy_score", "ai_score", "market_condition", "decision", "reason"
    ]

    # Упрощенные поля для сделок  
    TRADES_FIELDS = [
        "timestamp_open", "timestamp_close", "symbol", "side",
        "entry_price", "exit_price", "qty_usd", "pnl_pct", "pnl_abs", 
        "duration_minutes", "reason", "buy_score", "ai_score"
    ]

    # Кэш для чтения файлов
    _read_cache = {}
    _cache_ttl = 30  # секунд
    
    @staticmethod
    def log_signal_snapshot(data: Dict[str, Any]):
        """Логирование сигнала с батчингом"""
        try:
            # Добавляем timestamp если нет
            if "timestamp" not in data:
                data["timestamp"] = datetime.now().isoformat()
                
            _csv_batcher.add_record(SIGNALS_CSV, CSVHandler.SIGNALS_FIELDS, data)
            logging.debug("📊 Signal logged to batch")
            
        except Exception as e:
            logging.error(f"Failed to log signal: {e}")
    
    @staticmethod  
    def log_close_trade(data: Dict[str, Any]):
        """Логирование закрытой сделки с батчингом"""
        try:
            # Адаптация данных под упрощенную схему
            adapted = {
                "timestamp_open": data.get("entry_ts", ""),
                "timestamp_close": data.get("close_ts", datetime.now().isoformat()),
                "symbol": data.get("symbol", ""),
                "side": data.get("side", "LONG"),
                "entry_price": data.get("entry_price", 0.0),
                "exit_price": data.get("exit_price", 0.0),
                "qty_usd": data.get("qty_usd", 0.0),
                "pnl_pct": data.get("pnl_pct", 0.0),
                "pnl_abs": data.get("pnl_abs", 0.0),
                "duration_minutes": data.get("duration_minutes", 0.0),
                "reason": data.get("reason", ""),
                "buy_score": data.get("buy_score"),
                "ai_score": data.get("ai_score")
            }
            
            _csv_batcher.add_record(CLOSED_TRADES_CSV, CSVHandler.TRADES_FIELDS, adapted)
            logging.debug("💰 Trade logged to batch")
            
        except Exception as e:
            logging.error(f"Failed to log trade: {e}")

    @staticmethod
    def read_csv_cached(file_path: str, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Чтение CSV с кэшированием"""
        if not os.path.exists(file_path):
            return []
            
        # Проверяем кэш
        if use_cache and file_path in CSVHandler._read_cache:
            cached_data, cached_time, cached_mtime = CSVHandler._read_cache[file_path]
            current_mtime = os.path.getmtime(file_path)
            
            # Кэш валиден если файл не изменился и не истек TTL
            if (time.time() - cached_time < CSVHandler._cache_ttl and 
                current_mtime == cached_mtime):
                return cached_data.copy()
        
        # Читаем файл
        try:
            with open(file_path, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            
            # Сохраняем в кэш
            if use_cache:
                mtime = os.path.getmtime(file_path)
                CSVHandler._read_cache[file_path] = (data.copy(), time.time(), mtime)
            
            return data
            
        except Exception as e:
            logging.error(f"Failed to read CSV {file_path}: {e}")
            return []

    @staticmethod
    def read_csv_safe(file_path: str) -> List[Dict[str, Any]]:
        """Безопасное чтение с кэшированием"""
        return CSVHandler.read_csv_cached(file_path, use_cache=True)

    @staticmethod
    def read_last_trades(limit: int = 5) -> List[Dict[str, Any]]:
        """Последние сделки с оптимизацией"""
        try:
            trades = CSVHandler.read_csv_cached(CLOSED_TRADES_CSV, use_cache=True)
            
            # Фильтруем завершенные сделки
            completed = []
            for trade in trades:
                exit_price = trade.get("exit_price", "")
                if exit_price and str(exit_price).strip() and str(exit_price) != "0.0":
                    completed.append(trade)
            
            return completed[-limit:] if completed else []
            
        except Exception as e:
            logging.error(f"Failed to get last trades: {e}")
            return []

    @staticmethod
    def get_trade_stats() -> Dict[str, Any]:
        """Оптимизированная статистика по сделкам"""
        try:
            trades = CSVHandler.read_csv_cached(CLOSED_TRADES_CSV, use_cache=True)
            if not trades:
                return {"count": 0, "win_rate": 0, "avg_pnl": 0}

            # Эффективная фильтрация и расчет
            valid_pnl = []
            for trade in trades:
                exit_price = trade.get("exit_price", "")
                if exit_price and str(exit_price).strip():
                    try:
                        pnl = float(trade.get("pnl_pct", 0))
                        valid_pnl.append(pnl)
                    except (ValueError, TypeError):
                        continue

            if not valid_pnl:
                return {"count": 0, "win_rate": 0, "avg_pnl": 0}

            # Быстрые векторные вычисления
            import numpy as np
            pnl_array = np.array(valid_pnl)
            wins = pnl_array[pnl_array > 0]
            
            return {
                "count": len(valid_pnl),
                "win_rate": round((len(wins) / len(valid_pnl)) * 100, 2),
                "avg_pnl": round(np.mean(pnl_array), 2),
                "total_pnl": round(np.sum(pnl_array), 2),
                "wins": len(wins),
                "losses": len(valid_pnl) - len(wins),
                "best_trade": round(np.max(pnl_array), 2),
                "worst_trade": round(np.min(pnl_array), 2)
            }
            
        except Exception as e:
            logging.error(f"Failed to calculate trade stats: {e}")
            return {"count": 0, "win_rate": 0, "avg_pnl": 0}

    @staticmethod
    def get_csv_info(file_path: str) -> Dict[str, Any]:
        """Информация о CSV файле с кэшированием"""
        try:
            if not os.path.exists(file_path):
                return {"exists": False}
            
            # Быстрая проверка без полного чтения
            file_stats = os.stat(file_path)
            
            # Читаем только если файл небольшой
            if file_stats.st_size < 1024 * 1024:  # < 1MB
                data = CSVHandler.read_csv_cached(file_path, use_cache=True)
                columns = list(data[0].keys()) if data else []
                rows = len(data)
            else:
                # Для больших файлов - только подсчет строк
                with open(file_path, 'r', encoding='utf-8') as f:
                    rows = sum(1 for _ in f) - 1  # -1 для заголовка
                    f.seek(0)
                    first_line = f.readline()
                    columns = first_line.strip().split(',') if first_line else []
            
            return {
                "exists": True,
                "rows": rows,
                "columns": columns,
                "file_size_kb": round(file_stats.st_size / 1024, 2),
                "modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat()
            }
            
        except Exception as e:
            return {"exists": True, "error": str(e)}

    @staticmethod
    def force_flush():
        """Принудительно сбросить все буферы"""
        _csv_batcher.force_flush()
        logging.info("📄 CSV buffers flushed manually")

    @staticmethod
    def get_batch_stats() -> Dict[str, Any]:
        """Статистика батчинга"""
        return _csv_batcher.get_stats()

    @staticmethod
    def clear_cache():
        """Очистить кэш чтения"""
        CSVHandler._read_cache.clear()
        logging.info("📄 CSV read cache cleared")

    @staticmethod 
    def optimize_csv_file(file_path: str) -> bool:
        """Оптимизация CSV файла (удаление дубликатов, сортировка)"""
        try:
            if not os.path.exists(file_path):
                return False
                
            # Читаем данные
            data = CSVHandler.read_csv_cached(file_path, use_cache=False)
            if not data:
                return False
            
            # Создаем DataFrame для оптимизации
            df = pd.DataFrame(data)
            
            # Удаляем дубликаты
            initial_size = len(df)
            df = df.drop_duplicates()
            
            # Сортируем по timestamp если есть
            timestamp_cols = [col for col in df.columns if 'timestamp' in col.lower()]
            if timestamp_cols:
                try:
                    df[timestamp_cols[0]] = pd.to_datetime(df[timestamp_cols[0]], errors='coerce')
                    df = df.sort_values(timestamp_cols[0])
                except Exception:
                    pass
            
            # Создаем бэкап
            backup_path = f"{file_path}.backup"
            os.rename(file_path, backup_path)
            
            # Записываем оптимизированные данные
            df.to_csv(file_path, index=False)
            
            # Удаляем бэкап если все ОК
            os.remove(backup_path)
            
            removed = initial_size - len(df)
            if removed > 0:
                logging.info(f"📄 Optimized {file_path}: removed {removed} duplicates")
            
            # Очищаем кэш для этого файла
            if file_path in CSVHandler._read_cache:
                del CSVHandler._read_cache[file_path]
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to optimize CSV {file_path}: {e}")
            # Восстанавливаем из бэкапа если есть
            backup_path = f"{file_path}.backup"
            if os.path.exists(backup_path):
                os.rename(backup_path, file_path)
            return False

# =============================================================================
# УТИЛИТЫ МОНИТОРИНГА
# =============================================================================

def get_csv_system_stats() -> Dict[str, Any]:
    """Общая статистика CSV системы"""
    return {
        "batch_writer": _csv_batcher.get_stats(),
        "read_cache": {
            "size": len(CSVHandler._read_cache),
            "files": list(CSVHandler._read_cache.keys())
        },
        "files": {
            "signals": CSVHandler.get_csv_info(SIGNALS_CSV),
            "trades": CSVHandler.get_csv_info(CLOSED_TRADES_CSV)
        }
    }

def maintenance_csv_system():
    """Обслуживание CSV системы"""
    try:
        # Принудительный flush
        CSVHandler.force_flush()
        
        # Очистка кэша
        CSVHandler.clear_cache()
        
        # Оптимизация файлов (если не слишком большие)
        for file_path in [SIGNALS_CSV, CLOSED_TRADES_CSV]:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if file_size > 1024 * 1024:  # > 1MB
                    CSVHandler.optimize_csv_file(file_path)
        
        logging.info("📄 CSV system maintenance completed")
        return True
        
    except Exception as e:
        logging.error(f"CSV maintenance failed: {e}")
        return False

# =============================================================================
# СОВМЕСТИМОСТЬ И МИГРАЦИЯ
# =============================================================================

# Алиасы для обратной совместимости
def log_signal(data):
    """Алиас для совместимости"""
    return CSVHandler.log_signal_snapshot(data)

def log_closed_trade(data):
    """Алиас для совместимости"""
    return CSVHandler.log_close_trade(data)

def read_csv(file_path):
    """Алиас для совместимости"""
    return CSVHandler.read_csv_safe(file_path)

# Автоинициализация при импорте
try:
    os.makedirs(LOGS_DIR, exist_ok=True)
    logging.info("📄 Optimized CSV Handler initialized with batching")
except Exception as e:
    logging.error(f"CSV Handler initialization failed: {e}")

# Экспорт
__all__ = [
    'CSVHandler',
    'get_csv_system_stats', 
    'maintenance_csv_system',
    '_csv_batcher'  # Для тестирования
]