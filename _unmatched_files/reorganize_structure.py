#!/usr/bin/env python3
"""
Скрипт для реорганизации структуры проекта crypto-ai-bot
Запуск: python reorganize_structure.py
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Базовый путь к проекту
BASE_PATH = Path(r"C:\Users\satis\Documents\GitHub\crypto-ai-bot")
BACKUP_PATH = BASE_PATH / "_backup_old_structure"
UNMATCHED_PATH = BASE_PATH / "_unmatched_files"

# Новая структура проекта
NEW_STRUCTURE = {
    "src/crypto_ai_bot/app": [
        "server.py",
        "adapters/telegram.py"
    ],
    "src/crypto_ai_bot/core": [
        "settings.py",
        "types.py",
        "bot.py",
        "orchestrator.py"
    ],
    "src/crypto_ai_bot/core/indicators": [
        "unified.py"
    ],
    "src/crypto_ai_bot/core/signals": [
        "aggregator.py",
        "validator.py",
        "fusion.py",
        "policy.py"
    ],
    "src/crypto_ai_bot/core/risk": [
        "rules.py",
        "manager.py"
    ],
    "src/crypto_ai_bot/core/positions": [
        "manager.py",
        "tracker.py"
    ],
    "src/crypto_ai_bot/core/brokers": [
        "ccxt_exchange.py",
        "__init__.py"
    ],
    "src/crypto_ai_bot/core/storage/repositories": [
        "trades.py",
        "positions.py",
        "snapshots.py"
    ],
    "src/crypto_ai_bot/core/storage": [
        "sqlite_adapter.py"
    ],
    "src/crypto_ai_bot/core/storage/migrations": [
        "csv_to_sqlite.py"
    ],
    "src/crypto_ai_bot/core/events": [
        "bus.py"
    ],
    "src/crypto_ai_bot/utils": [
        "http_client.py",
        "cache.py",
        "logging.py"
    ],
    "src/crypto_ai_bot/io": [
        "csv_handler.py"
    ],
    "analysis": [],
    "notebooks": []
}

# Маппинг старых файлов на новые локации
FILE_MAPPING = {
    # App layer
    "src/app/server.py": "src/crypto_ai_bot/app/server.py",
    "src/app/health.py": "src/crypto_ai_bot/app/server.py",  # объединить с server.py
    "src/telegram/bot.py": "src/crypto_ai_bot/app/adapters/telegram.py",
    "src/telegram/handler.py": "src/crypto_ai_bot/app/adapters/telegram.py",
    
    # Core
    "src/core/settings.py": "src/crypto_ai_bot/core/settings.py",
    "src/core/types/__init__.py": "src/crypto_ai_bot/core/types.py",
    "src/core/bot.py": "src/crypto_ai_bot/core/bot.py",
    "src/trading/bot.py": "src/crypto_ai_bot/core/bot.py",  # дубликат
    "src/core/orchestrator.py": "src/crypto_ai_bot/core/orchestrator.py",
    
    # Indicators
    "src/core/indicators/unified.py": "src/crypto_ai_bot/core/indicators/unified.py",
    
    # Signals
    "src/core/signals/aggregator.py": "src/crypto_ai_bot/core/signals/aggregator.py",
    "src/core/signals/validator.py": "src/crypto_ai_bot/core/signals/validator.py",
    "src/core/signals/policy.py": "src/crypto_ai_bot/core/signals/policy.py",
    
    # Risk
    "src/core/risk/manager.py": "src/crypto_ai_bot/core/risk/manager.py",
    "src/trading/risk.py": "src/crypto_ai_bot/core/risk/rules.py",
    
    # Positions
    "src/core/positions/manager.py": "src/crypto_ai_bot/core/positions/manager.py",
    "src/src/crypto_ai_bot/core/positions/tracker.py": "src/crypto_ai_bot/core/positions/tracker.py",
    "src/trading/performance_tracker.py": "src/crypto_ai_bot/core/positions/tracker.py",
    
    # Brokers
    "src/core/brokers/ccxt_exchange.py": "src/crypto_ai_bot/core/brokers/ccxt_exchange.py",
    "src/trading/exchange_client.py": "src/crypto_ai_bot/core/brokers/ccxt_exchange.py",
    "src/crypto_ai_bot/trading/exchange_client.py": "src/crypto_ai_bot/core/brokers/ccxt_exchange.py",
    
    # Storage
    "src/storage/repositories/trades.py": "src/crypto_ai_bot/core/storage/repositories/trades.py",
    "src/storage/repositories/positions.py": "src/crypto_ai_bot/core/storage/repositories/positions.py",
    "src/storage/repositories/snapshots.py": "src/crypto_ai_bot/core/storage/repositories/snapshots.py",
    "src/storage/repositories/sqlite_adapter.py": "src/crypto_ai_bot/core/storage/sqlite_adapter.py",
    "src/storage/migrations/csv_to_sqlite.py": "src/crypto_ai_bot/core/storage/migrations/csv_to_sqlite.py",
    "src/storage/storage/migrations/csv_to_sqlite.py": "src/crypto_ai_bot/core/storage/migrations/csv_to_sqlite.py",
    
    # Events
    "src/core/events/bus.py": "src/crypto_ai_bot/core/events/bus.py",
    
    # Utils
    "src/utils/http_client.py": "src/crypto_ai_bot/utils/http_client.py",
    "src/utils/cache.py": "src/crypto_ai_bot/utils/cache.py",
    "src/cache.py": "src/crypto_ai_bot/utils/cache.py",
    "src/src/crypto_ai_bot/utils/logging.py": "src/crypto_ai_bot/utils/logging.py",
    
    # IO
    "src/io/csv_handler.py": "src/crypto_ai_bot/io/csv_handler.py",
    
    # Analysis
    "src/analysis/market_analyzer.py": "analysis/market_analyzer.py",
    "src/analysis/scoring_engine.py": "analysis/scoring_engine.py",
    
    # ML
    "src/ml/adaptive_model.py": "analysis/adaptive_model.py",
}

def create_directory_structure():
    """Создает новую структуру директорий"""
    logger.info("Создание новой структуры директорий...")
    
    for dir_path in NEW_STRUCTURE.keys():
        full_path = BASE_PATH / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Создана директория: {full_path}")
    
    # Создаем папку для неподходящих файлов
    UNMATCHED_PATH.mkdir(exist_ok=True)
    logger.info(f"Создана папка для неподходящих файлов: {UNMATCHED_PATH}")

def backup_current_structure():
    """Создает резервную копию текущей структуры"""
    if BACKUP_PATH.exists():
        logger.warning(f"Резервная копия уже существует: {BACKUP_PATH}")
        response = input("Удалить старую резервную копию? (y/n): ")
        if response.lower() == 'y':
            shutil.rmtree(BACKUP_PATH)
        else:
            logger.error("Отмена операции")
            exit(1)
    
    logger.info("Создание резервной копии...")
    shutil.copytree(BASE_PATH / "src", BACKUP_PATH / "src", dirs_exist_ok=True)
    logger.info(f"Резервная копия создана: {BACKUP_PATH}")

def get_unique_filename(target_path: Path) -> Path:
    """Генерирует уникальное имя файла, если файл уже существует"""
    if not target_path.exists():
        return target_path
    
    counter = 2
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    
    while True:
        new_name = parent / f"{stem}{counter}{suffix}"
        if not new_name.exists():
            return new_name
        counter += 1

def move_file(source: Path, target: Path):
    """Перемещает файл с обработкой дубликатов"""
    if not source.exists():
        logger.debug(f"Файл не существует: {source}")
        return
    
    # Проверяем, не тот же ли это файл
    if source.resolve() == target.resolve():
        logger.debug(f"Источник и цель совпадают: {source}")
        return
    
    # Создаем директорию если нужно
    target.parent.mkdir(parents=True, exist_ok=True)
    
    # Проверяем на дубликаты
    if target.exists():
        target = get_unique_filename(target)
        logger.warning(f"Файл уже существует, переименован: {target.name}")
    
    try:
        shutil.move(str(source), str(target))
        logger.info(f"Перемещен: {source.relative_to(BASE_PATH)} → {target.relative_to(BASE_PATH)}")
    except Exception as e:
        logger.error(f"Ошибка при перемещении {source}: {e}")

def reorganize_files():
    """Реорганизует файлы согласно маппингу"""
    logger.info("Начинаем реорганизацию файлов...")
    
    moved_files = set()
    
    # Перемещаем файлы согласно маппингу
    for old_path, new_path in FILE_MAPPING.items():
        source = BASE_PATH / old_path
        target = BASE_PATH / new_path
        
        if source.exists():
            move_file(source, target)
            moved_files.add(str(source.relative_to(BASE_PATH)))
    
    # Находим все Python файлы, которые не были перемещены
    logger.info("Поиск неперемещенных файлов...")
    for py_file in BASE_PATH.rglob("*.py"):
        relative_path = str(py_file.relative_to(BASE_PATH))
        
        # Пропускаем файлы в новой структуре, резервной копии и неподходящих
        if (relative_path.startswith("src/crypto_ai_bot/") or 
            relative_path.startswith("_backup_") or
            relative_path.startswith("_unmatched_") or
            relative_path.startswith("analysis/") or
            relative_path.startswith("notebooks/") or
            relative_path in moved_files):
            continue
        
        # Перемещаем в папку неподходящих файлов
        target = UNMATCHED_PATH / py_file.relative_to(BASE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.move(str(py_file), str(target))
            logger.warning(f"Неподходящий файл перемещен в _unmatched_files: {relative_path}")
        except Exception as e:
            logger.error(f"Ошибка при перемещении {py_file}: {e}")

def cleanup_empty_directories():
    """Удаляет пустые директории в старой структуре"""
    logger.info("Удаление пустых директорий...")
    
    for dirpath, dirnames, filenames in os.walk(BASE_PATH / "src", topdown=False):
        dirpath = Path(dirpath)
        
        # Пропускаем новую структуру
        if "crypto_ai_bot" in str(dirpath):
            continue
            
        # Если директория пуста, удаляем
        if not any(dirpath.iterdir()):
            try:
                dirpath.rmdir()
                logger.debug(f"Удалена пустая директория: {dirpath}")
            except:
                pass

def main():
    """Главная функция"""
    print("=" * 60)
    print("РЕОРГАНИЗАЦИЯ СТРУКТУРЫ ПРОЕКТА crypto-ai-bot")
    print("=" * 60)
    
    # Проверяем, что мы в правильной директории
    if not BASE_PATH.exists():
        logger.error(f"Директория проекта не найдена: {BASE_PATH}")
        return
    
    os.chdir(BASE_PATH)
    
    # Подтверждение от пользователя
    print(f"\nБазовая директория: {BASE_PATH}")
    print(f"Резервная копия будет создана в: {BACKUP_PATH}")
    print(f"Неподходящие файлы будут перемещены в: {UNMATCHED_PATH}")
    
    response = input("\nПродолжить? (y/n): ")
    if response.lower() != 'y':
        logger.info("Операция отменена пользователем")
        return
    
    try:
        # 1. Создаем резервную копию
        backup_current_structure()
        
        # 2. Создаем новую структуру
        create_directory_structure()
        
        # 3. Реорганизуем файлы
        reorganize_files()
        
        # 4. Удаляем пустые директории
        cleanup_empty_directories()
        
        print("\n" + "=" * 60)
        print("РЕОРГАНИЗАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 60)
        print(f"\n✓ Резервная копия сохранена в: {BACKUP_PATH}")
        print(f"✓ Неподходящие файлы в: {UNMATCHED_PATH}")
        print("\nРекомендации:")
        print("1. Проверьте файлы в папке _unmatched_files")
        print("2. Обновите импорты в файлах")
        print("3. Проверьте работоспособность проекта")
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print("\nПри необходимости восстановите из резервной копии")

if __name__ == "__main__":
    main()