# utils/csv_handler.py - UNIFIED CACHE VERSION (ЭТАП 3)

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

# ✅ ЭТАП 3: UNIFIED CACHE INTEGRATION
try:
    from utils.unified_cache import get_cache_manager, CacheNamespace
    UNIFIED_CACHE_AVAILABLE = True
    logging.info("📄 CSV Handler: Unified Cache Manager loaded")
except ImportError:
    UNIFIED_CACHE_AVAILABLE = False
    logging.warning("📄 CSV Handler: Unified Cache not available, using fallback")

# =============================================================================
# СИСТЕМА БАТЧИНГА CSV ЗАПИСЕЙ (без изменений)
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
        self._thread = None
        self._stop = threading.Event()
        self._started = False
    
    def add_record(self, file_path: str, fieldnames: List[str], data: Dict[str, Any]):
        """Добавить запись в буфер"""
        with self._lock:
            self._buffer.append(CSVRecord(file_path, fieldnames, data))
            self._total_records += 1
            
            # Немедленный flush при превышении размера батча
            if len(self._buffer) >= self.batch_size:
                self._flush_buffer()
    
    def _background_flush_loop(self):
        """Фоновая петля сброса буфера (управляется start/stop)"""
        while not self._stop.is_set():
            time.sleep(self.flush_interval)
            with self._lock:
                if self._buffer and time.time() - self._last_flush > self.flush_interval:
                    self._flush_buffer()
        # финальный flush на выходе
        with self._lock:
            if self._buffer:
                self._flush_buffer()
        logging.debug("📄 Background CSV flusher stopped")
    
    def start(self) -> bool:
        """Явный запуск фонового флашера (идемпотентно)."""
        if getattr(self, "_started", False):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._background_flush_loop, daemon=True, name="CSVBatchFlusher")
        self._thread.start()
        self._started = True
        logging.debug("📄 Background CSV flusher started")
        return True
    
    def stop(self, timeout: float = 2.0) -> bool:
        """Остановка фонового флашера с ожиданием."""
        if not getattr(self, "_started", False):
            return False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._started = False
        return True
    
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
# ✅ ЭТАП 3: CSV HANDLER С UNIFIED CACHE
# =============================================================================

class CSVHandler:
    """CSV обработчик с UNIFIED CACHE системой"""
    
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

    # ✅ НОВОЕ: Unified Cache вместо _read_cache
    @staticmethod
    def _get_cache_manager():
        """Получить unified cache manager с fallback"""
        if UNIFIED_CACHE_AVAILABLE:
            return get_cache_manager()
        return None

    @staticmethod 
    def _create_cache_key(file_path: str, use_mtime: bool = True) -> str:
        """Создание ключа кэша с учетом времени модификации файла"""
        try:
            if use_mtime and os.path.exists(file_path):
                mtime = os.path.getmtime(file_path)
                file_size = os.path.getsize(file_path)
                return f"{file_path}:{mtime}:{file_size}"
            else:
                return file_path
        except Exception:
            return file_path
    
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
        """✅ ЭТАП 3: Чтение CSV с UNIFIED CACHE"""
        if not os.path.exists(file_path):
            return []
        
        # ✅ Используем unified cache если доступен
        cache_manager = CSVHandler._get_cache_manager()
        
        if use_cache and cache_manager and UNIFIED_CACHE_AVAILABLE:
            # Создаем ключ с учетом времени модификации
            cache_key = CSVHandler._create_cache_key(file_path, use_mtime=True)
            
            # Проверяем unified cache
            cached_data = cache_manager.get(cache_key, CacheNamespace.CSV_READS)
            if cached_data is not None:
                logging.debug(f"📄 CSV Cache HIT (unified): {file_path}")
                return cached_data.copy()
        
        # Читаем файл с диска
        try:
            with open(file_path, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            
            # ✅ Сохраняем в unified cache
            if use_cache and cache_manager and UNIFIED_CACHE_AVAILABLE:
                cache_key = CSVHandler._create_cache_key(file_path, use_mtime=True)
                success = cache_manager.set(
                    cache_key, 
                    data.copy(), 
                    CacheNamespace.CSV_READS,
                    metadata={"file_path": file_path, "rows": len(data)}
                )
                if success:
                    logging.debug(f"📄 CSV Cache SET (unified): {file_path} ({len(data)} rows)")
                else:
                    logging.warning(f"📄 CSV Cache SET failed: {file_path}")
            
            return data
            
        except Exception as e:
            logging.error(f"Failed to read CSV {file_path}: {e}")
            return []

    @staticmethod
    def read_csv_safe(file_path: str) -> List[Dict[str, Any]]:
        """Безопасное чтение с unified кэшированием"""
        return CSVHandler.read_csv_cached(file_path, use_cache=True)

    @staticmethod
    def read_last_trades(limit: int = 5) -> List[Dict[str, Any]]:
        """Последние сделки с unified cache оптимизацией"""
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
        """Оптимизированная статистика по сделкам с unified cache"""
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
        """Информация о CSV файле с unified кэшированием"""
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
        """✅ ЭТАП 3: Очистить unified cache CSV namespace"""
        cache_manager = CSVHandler._get_cache_manager()
        
        if cache_manager and UNIFIED_CACHE_AVAILABLE:
            # Очищаем весь namespace CSV_READS
            cache_manager.clear_namespace(CacheNamespace.CSV_READS)
            logging.info("📄 CSV unified cache cleared (namespace CSV_READS)")
        else:
            logging.info("📄 CSV cache clear skipped: unified cache not available")

    @staticmethod 
    def optimize_csv_file(file_path: str) -> bool:
        """Оптимизация CSV файла (удаление дубликатов, сортировка)"""
        try:
            if not os.path.exists(file_path):
                return False
                
            # Читаем данные (не из кэша для оптимизации)
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
            
            # ✅ Очищаем unified cache для этого файла
            CSVHandler._invalidate_file_cache(file_path)
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to optimize CSV {file_path}: {e}")
            # Восстанавливаем из бэкапа если есть
            backup_path = f"{file_path}.backup"
            if os.path.exists(backup_path):
                os.rename(backup_path, file_path)
            return False

    @staticmethod
    def _invalidate_file_cache(file_path: str):
        """✅ НОВОЕ: Инвалидация кэша для конкретного файла"""
        cache_manager = CSVHandler._get_cache_manager()
        
        if cache_manager and UNIFIED_CACHE_AVAILABLE:
            # Создаем различные возможные ключи для файла
            possible_keys = [
                CSVHandler._create_cache_key(file_path, use_mtime=True),
                CSVHandler._create_cache_key(file_path, use_mtime=False),
                file_path
            ]
            
            for key in possible_keys:
                cache_manager.delete(key, CacheNamespace.CSV_READS)
            
            logging.debug(f"📄 Invalidated unified cache for: {file_path}")

    # =========================================================================
    # ✅ НОВЫЕ МЕТОДЫ: UNIFIED CACHE ДИАГНОСТИКА
    # =========================================================================

    @staticmethod
    def get_cache_diagnostics() -> Dict[str, Any]:
        """✅ НОВОЕ: Диагностика unified cache для CSV"""
        cache_manager = CSVHandler._get_cache_manager()
        
        if not cache_manager or not UNIFIED_CACHE_AVAILABLE:
            return {
                "unified_cache_available": False,
                "fallback_mode": True
            }
        
        try:
            # Получаем общую статистику
            stats = cache_manager.get_stats()
            
            # Получаем топ ключей для CSV namespace
            top_keys = cache_manager.get_top_keys(CacheNamespace.CSV_READS, limit=5)
            
            return {
                "unified_cache_available": True,
                "csv_namespace_stats": stats["namespaces"].get("csv_reads", {}),
                "global_stats": stats["global"],
                "top_csv_keys": top_keys,
                "memory_pressure": stats["memory_pressure"]
            }
            
        except Exception as e:
            return {
                "unified_cache_available": True,
                "error": str(e)
            }

    @staticmethod
    def test_unified_cache_integration():
        """✅ НОВОЕ: Тестирование unified cache интеграции"""
        cache_manager = CSVHandler._get_cache_manager()
        
        if not cache_manager or not UNIFIED_CACHE_AVAILABLE:
            return {
                "test_passed": False,
                "reason": "Unified cache not available"
            }
        
        try:
            # Тестовые данные
            test_key = "test_csv_file.csv"
            test_data = [{"col1": "value1", "col2": "value2"}]
            
            # Тест SET
            set_success = cache_manager.set(test_key, test_data, CacheNamespace.CSV_READS)
            
            # Тест GET
            retrieved_data = cache_manager.get(test_key, CacheNamespace.CSV_READS)
            
            # Тест DELETE
            delete_success = cache_manager.delete(test_key, CacheNamespace.CSV_READS)
            
            test_passed = (
                set_success and 
                retrieved_data == test_data and 
                delete_success
            )
            
            return {
                "test_passed": test_passed,
                "set_success": set_success,
                "get_success": retrieved_data == test_data,
                "delete_success": delete_success,
                "cache_stats": cache_manager.get_stats()["namespaces"].get("csv_reads", {})
            }
            
        except Exception as e:
            return {
                "test_passed": False,
                "error": str(e)
            }

# =============================================================================
# УТИЛИТЫ МОНИТОРИНГА (обновленные)
# =============================================================================

def get_csv_system_stats() -> Dict[str, Any]:
    """✅ ОБНОВЛЕНО: Общая статистика CSV системы с unified cache"""
    base_stats = {
        "batch_writer": _csv_batcher.get_stats(),
        "files": {
            "signals": CSVHandler.get_csv_info(SIGNALS_CSV),
            "trades": CSVHandler.get_csv_info(CLOSED_TRADES_CSV)
        }
    }
    
    # ✅ Добавляем unified cache статистику
    cache_diagnostics = CSVHandler.get_cache_diagnostics()
    base_stats["unified_cache"] = cache_diagnostics
    
    return base_stats

def maintenance_csv_system():
    """✅ ОБНОВЛЕНО: Обслуживание CSV системы с unified cache"""
    try:
        # Принудительный flush
        CSVHandler.force_flush()
        
        # ✅ Очистка unified cache
        CSVHandler.clear_cache()
        
        # Оптимизация файлов (если не слишком большие)
        for file_path in [SIGNALS_CSV, CLOSED_TRADES_CSV]:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if file_size > 1024 * 1024:  # > 1MB
                    CSVHandler.optimize_csv_file(file_path)
        
        logging.info("📄 CSV system maintenance completed (with unified cache)")
        return True
        
    except Exception as e:
        logging.error(f"CSV maintenance failed: {e}")
        return False

# =============================================================================
# СОВМЕСТИМОСТЬ И МИГРАЦИЯ (без изменений)
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
    
    # ✅ Проверяем unified cache при инициализации
    if UNIFIED_CACHE_AVAILABLE:
        test_result = CSVHandler.test_unified_cache_integration()
        if test_result["test_passed"]:
            logging.info("📄 CSV Handler initialized with UNIFIED CACHE (✅ test passed)")
        else:
            logging.warning(f"📄 CSV Handler: unified cache test failed - {test_result}")
    else:
        logging.info("📄 CSV Handler initialized in FALLBACK mode")
        
except Exception as e:
    logging.error(f"CSV Handler initialization failed: {e}")

# Экспорт
__all__ = [
    'CSVHandler',
    'get_csv_system_stats', 
    'maintenance_csv_system',
    '_csv_batcher'  # Для тестирования
]