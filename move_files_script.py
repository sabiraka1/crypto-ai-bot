#!/usr/bin/env python3
"""
Скрипт для перемещения файлов из _unmatched_files в правильную структуру
"""

import os
import shutil
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

BASE_PATH = Path(r"C:\Users\satis\Documents\GitHub\crypto-ai-bot")
UNMATCHED_PATH = BASE_PATH / "_unmatched_files"
TARGET_PATH = BASE_PATH / "src" / "crypto_ai_bot"

def move_files():
    """Перемещает файлы из _unmatched_files в основную структуру"""
    
    # Файлы для перемещения в основную структуру
    files_to_move = [
        # Core файлы
        ("src/crypto_ai_bot/app/server.py", "app/server.py"),
        ("src/crypto_ai_bot/app/adapters/telegram.py", "app/adapters/telegram.py"),
        
        ("src/crypto_ai_bot/core/settings.py", "core/settings.py"),
        ("src/crypto_ai_bot/core/types.py", "core/types.py"),
        ("src/crypto_ai_bot/core/bot.py", "core/bot.py"),
        ("src/crypto_ai_bot/core/orchestrator.py", "core/orchestrator.py"),
        
        ("src/crypto_ai_bot/core/indicators/unified.py", "core/indicators/unified.py"),
        
        ("src/crypto_ai_bot/core/signals/aggregator.py", "core/signals/aggregator.py"),
        ("src/crypto_ai_bot/core/signals/validator.py", "core/signals/validator.py"),
        ("src/crypto_ai_bot/core/signals/policy.py", "core/signals/policy.py"),
        
        ("src/crypto_ai_bot/core/risk/manager.py", "core/risk/manager.py"),
        ("src/crypto_ai_bot/core/risk/rules.py", "core/risk/rules.py"),
        
        ("src/crypto_ai_bot/core/positions/manager.py", "core/positions/manager.py"),
        ("src/crypto_ai_bot/core/positions/tracker.py", "core/positions/tracker.py"),
        
        ("src/crypto_ai_bot/core/brokers/ccxt_exchange.py", "core/brokers/ccxt_exchange.py"),
        
        ("src/crypto_ai_bot/core/storage/migrations/csv_to_sqlite.py", "core/storage/migrations/csv_to_sqlite.py"),
        
        ("src/crypto_ai_bot/core/events/bus.py", "core/events/bus.py"),
        
        ("src/crypto_ai_bot/utils/http_client.py", "utils/http_client.py"),
        ("src/crypto_ai_bot/utils/cache.py", "utils/cache.py"),
        ("src/crypto_ai_bot/utils/logging.py", "utils/logging.py"),
        
        ("src/crypto_ai_bot/io/csv_handler.py", "io/csv_handler.py"),
        
        # Дополнительные файлы из storage
        ("src/storage/storage/repositories/trades.py", "core/storage/repositories/trades.py"),
        ("src/storage/storage/repositories/positions.py", "core/storage/repositories/positions.py"),
        ("src/storage/storage/repositories/snapshots.py", "core/storage/repositories/snapshots.py"),
        ("src/storage/storage/repositories/sqlite_adapter.py", "core/storage/sqlite_adapter.py"),
        
        # Другие полезные файлы
        ("src/core/database.py", "core/database.py"),
        ("src/core/metrics.py", "core/metrics.py"),
        ("src/core/state_manager.py", "core/state_manager.py"),
        ("src/core/scheduler.py", "core/scheduler.py"),
        ("src/core/decorators.py", "core/decorators.py"),
        
        # Context файлы (могут пригодиться)
        ("src/context/snapshot.py", "core/context/snapshot.py"),
        ("src/context/market/btc_dominance.py", "core/context/market/btc_dominance.py"),
        ("src/context/market/correlation.py", "core/context/market/correlation.py"),
        ("src/context/market/dxy_index.py", "core/context/market/dxy_index.py"),
        ("src/context/market/fear_greed.py", "core/context/market/fear_greed.py"),
        ("src/context/regime/regime_detector.py", "core/context/regime_detector.py"),
        ("src/context/calendar/fomc.py", "core/context/fomc.py"),
        ("src/context/calendar/embargo_windows.py", "core/context/embargo_windows.py"),
        
        # Utils
        ("src/utils/envtools.py", "utils/envtools.py"),
        ("src/utils/validators.py", "utils/validators.py"),
        ("src/utils/trading_metrics.py", "utils/trading_metrics.py"),
        ("src/utils/integration_check.py", "utils/integration_check.py"),
        
        # Telegram
        ("src/telegram/charts.py", "app/adapters/charts.py"),
        
        # Trading (если нужно)
        ("src/trading/paper_store.py", "core/trading/paper_store.py"),
        
        # ML
        ("src/ml/adaptive_model.py", "ml/adaptive_model.py"),
        
        # Metrics
        ("src/metrics/collector.py", "metrics/collector.py"),
    ]
    
    moved_count = 0
    
    for source, target in files_to_move:
        source_path = UNMATCHED_PATH / source
        target_path = TARGET_PATH / target
        
        if source_path.exists():
            # Создаем директорию если нужно
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Если файл уже существует, добавляем номер
            if target_path.exists():
                stem = target_path.stem
                suffix = target_path.suffix
                counter = 2
                while target_path.exists():
                    target_path = target_path.parent / f"{stem}{counter}{suffix}"
                    counter += 1
                logger.warning(f"Файл уже существует, переименован в: {target_path.name}")
            
            try:
                shutil.move(str(source_path), str(target_path))
                logger.info(f"✓ Перемещен: {source} → {target}")
                moved_count += 1
            except Exception as e:
                logger.error(f"✗ Ошибка при перемещении {source}: {e}")
        else:
            logger.debug(f"Файл не найден: {source}")
    
    # Перемещаем файлы analysis в корень
    analysis_files = [
        ("analysis/market_analyzer.py", "../analysis/market_analyzer.py"),
        ("analysis/scoring_engine.py", "../analysis/scoring_engine.py"),
        ("analysis/adaptive_model.py", "../analysis/adaptive_model.py"),
    ]
    
    for source, target in analysis_files:
        source_path = UNMATCHED_PATH / source
        target_path = BASE_PATH / "analysis" / Path(target).name
        
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(source_path), str(target_path))
                logger.info(f"✓ Перемещен в analysis: {source}")
                moved_count += 1
            except Exception as e:
                logger.error(f"✗ Ошибка: {e}")
    
    # Перемещаем тесты
    tests_path = UNMATCHED_PATH / "tests"
    if tests_path.exists():
        target_tests = BASE_PATH / "tests_backup"
        try:
            shutil.move(str(tests_path), str(target_tests))
            logger.info(f"✓ Тесты перемещены в tests_backup")
        except Exception as e:
            logger.error(f"✗ Ошибка при перемещении тестов: {e}")
    
    # Создаем __init__.py файлы где нужно
    init_dirs = [
        TARGET_PATH / "app",
        TARGET_PATH / "app/adapters",
        TARGET_PATH / "core",
        TARGET_PATH / "core/indicators",
        TARGET_PATH / "core/signals",
        TARGET_PATH / "core/risk",
        TARGET_PATH / "core/positions",
        TARGET_PATH / "core/brokers",
        TARGET_PATH / "core/storage",
        TARGET_PATH / "core/storage/repositories",
        TARGET_PATH / "core/storage/migrations",
        TARGET_PATH / "core/events",
        TARGET_PATH / "core/context",
        TARGET_PATH / "utils",
        TARGET_PATH / "io",
    ]
    
    for dir_path in init_dirs:
        if dir_path.exists():
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.touch()
                logger.debug(f"Создан __init__.py в {dir_path}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Перемещено файлов: {moved_count}")
    logger.info(f"{'='*60}")

def main():
    print("=" * 60)
    print("ПЕРЕМЕЩЕНИЕ ФАЙЛОВ В НОВУЮ СТРУКТУРУ")
    print("=" * 60)
    
    if not UNMATCHED_PATH.exists():
        logger.error(f"Папка {UNMATCHED_PATH} не найдена!")
        return
    
    move_files()
    
    print("\n✓ Готово!")
    print("\nРекомендации:")
    print("1. Проверьте структуру: tree src\\crypto_ai_bot /F")
    print("2. Проверьте оставшиеся файлы в _unmatched_files")
    print("3. Обновите импорты в Python файлах")

if __name__ == "__main__":
    main()