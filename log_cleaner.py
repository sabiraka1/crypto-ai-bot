import pandas as pd
import os
from datetime import datetime, timedelta
import logging

SIGNAL_CSV = "sinyal_fiyat_analizi.csv"
CLOSED_CSV = "closed_trades.csv"
ERROR_CSV = "error_signals.csv"
CHARTS_DIR = "charts"
MODELS_DIR = "models"

logger = logging.getLogger(__name__)

def clean_csv(file_path, date_column, days=60):
    """Очистка CSV файла от старых записей"""
    if not os.path.exists(file_path):
        logger.info(f"📁 Файл {file_path} не найден")
        return

    try:
        df = pd.read_csv(file_path)
        
        if date_column not in df.columns:
            logger.warning(f"⚠️ Колонка {date_column} не найдена в {file_path}")
            return
            
        original_count = len(df)
        
        # Конвертируем в datetime
        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
        
        # Удаляем записи с некорректными датами
        df = df.dropna(subset=[date_column])
        
        # Фильтруем по дате
        cutoff = datetime.now() - timedelta(days=days)
        df_filtered = df[df[date_column] >= cutoff]
        
        # Сохраняем обратно
        df_filtered.to_csv(file_path, index=False)
        
        removed_count = original_count - len(df_filtered)
        logger.info(f"🧹 {file_path}: удалено {removed_count} записей, осталось {len(df_filtered)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка очистки {file_path}: {e}")

def clean_charts(days=3):
    """Очистка старых графиков"""
    if not os.path.exists(CHARTS_DIR):
        logger.info(f"📁 Директория {CHARTS_DIR} не найдена")
        return

    try:
        cutoff = datetime.now() - timedelta(days=days)
        removed_count = 0
        
        for filename in os.listdir(CHARTS_DIR):
            file_path = os.path.join(CHARTS_DIR, filename)
            
            if filename.endswith(('.png', '.jpg', '.jpeg')):
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    if file_mtime < cutoff:
                        os.remove(file_path)
                        removed_count += 1
                        
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка удаления {filename}: {e}")
        
        logger.info(f"🧹 Удалено {removed_count} старых графиков")
        
    except Exception as e:
        logger.error(f"❌ Ошибка очистки графиков: {e}")

def clean_old_models(keep_count=3):
    """Очистка старых моделей, оставляем последние N"""
    if not os.path.exists(MODELS_DIR):
        logger.info(f"📁 Директория {MODELS_DIR} не найдена")
        return

    try:
        model_files = []
        
        for filename in os.listdir(MODELS_DIR):
            if filename.endswith('.pkl'):
                file_path = os.path.join(MODELS_DIR, filename)
                file_mtime = os.path.getmtime(file_path)
                model_files.append((file_path, file_mtime, filename))
        
        # Сортируем по времени модификации (новые первыми)
        model_files.sort(key=lambda x: x[1], reverse=True)
        
        # Удаляем старые модели
        removed_count = 0
        for file_path, _, filename in model_files[keep_count:]:
            if 'backup' not in filename.lower():  # Не удаляем backup файлы
                try:
                    os.remove(file_path)
                    removed_count += 1
                    logger.info(f"🗑️ Удален старый файл модели: {filename}")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка удаления {filename}: {e}")
        
        logger.info(f"🧹 Удалено {removed_count} старых моделей")
        
    except Exception as e:
        logger.error(f"❌ Ошибка очистки моделей: {e}")

def clean_logs():
    """Основная функция очистки всех логов"""
    logger.info("🧹 Начинаю очистку логов и файлов...")
    
    # Очистка CSV файлов
    clean_csv(SIGNAL_CSV, "datetime", days=90)  # Сигналы за 3 месяца
    clean_csv(CLOSED_CSV, "close_datetime", days=365)  # Сделки за год
    clean_csv(ERROR_CSV, "timestamp", days=60)  # Ошибки за 2 месяца
    
    # Очистка графиков
    clean_charts(days=7)  # Графики за неделю
    
    # Очистка старых моделей
    clean_old_models(keep_count=5)  # Оставляем 5 последних моделей
    
    logger.info("✅ Очистка завершена")

def get_disk_usage():
    """Получение информации об использовании диска"""
    try:
        usage_info = {}
        
        # Размеры CSV файлов
        for file_path in [SIGNAL_CSV, CLOSED_CSV, ERROR_CSV]:
            if os.path.exists(file_path):
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                usage_info[file_path] = f"{size_mb:.1f} MB"
        
        # Размер директории с графиками
        if os.path.exists(CHARTS_DIR):
            total_size = sum(
                os.path.getsize(os.path.join(CHARTS_DIR, f))
                for f in os.listdir(CHARTS_DIR)
                if os.path.isfile(os.path.join(CHARTS_DIR, f))
            )
            usage_info[CHARTS_DIR] = f"{total_size / (1024 * 1024):.1f} MB"
        
        # Размер директории с моделями
        if os.path.exists(MODELS_DIR):
            total_size = sum(
                os.path.getsize(os.path.join(MODELS_DIR, f))
                for f in os.listdir(MODELS_DIR)
                if os.path.isfile(os.path.join(MODELS_DIR, f))
            )
            usage_info[MODELS_DIR] = f"{total_size / (1024 * 1024):.1f} MB"
        
        return usage_info
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации о диске: {e}")
        return {}

def cleanup_emergency():
    """Экстренная очистка при нехватке места"""
    logger.warning("🚨 Запуск экстренной очистки!")
    
    # Более агрессивная очистка
    clean_csv(SIGNAL_CSV, "datetime", days=30)  # Только месяц сигналов
    clean_csv(ERROR_CSV, "timestamp", days=14)  # Только 2 недели ошибок
    
    # Удаляем все графики старше суток
    clean_charts(days=1)
    
    # Оставляем только 2 последние модели
    clean_old_models(keep_count=2)
    
    logger.info("✅ Экстренная очистка завершена")

def schedule_cleanup():
    """Функция для планировщика - запускается автоматически"""
    try:
        logger.info("⏰ Запуск запланированной очистки")
        clean_logs()
        
        # Получаем статистику
        usage = get_disk_usage()
        logger.info("📊 Использование диска после очистки:")
        for path, size in usage.items():
            logger.info(f"  {path}: {size}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка в запланированной очистке: {e}")

if __name__ == "__main__":
    # Настройка логирования для standalone запуска
    logging.basicConfig(level=logging.INFO)
    clean_logs()
