"""Улучшенные тесты для класса StateManager."""
import tempfile
import os
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, mock_open
import pytest

from core.state_manager import StateManager, TradingState


class TestStateManager:
    """Комплексные тесты StateManager с различными сценариями."""

    def test_set_and_get_calls_atomic_write(self, tmp_path):
        """Проверяем атомарную запись при установке значения."""
        state_file = tmp_path / "state.json"
        sm = StateManager(str(state_file))
        
        with patch.object(sm, "_atomic_write") as mock_write:
            sm.set("key", "value")
            mock_write.assert_called_once()
        
        assert sm.get("key") == "value"

    def test_cooldown_logic(self, tmp_path):
        """Проверяем корректность работы кулдауна."""
        state_file = tmp_path / "state.json"
        sm = StateManager(str(state_file))
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        with patch("core.state_manager.datetime") as mock_dt:
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            # Запускаем кулдаун на 60 секунд
            sm.start_cooldown(seconds=60)
            
            # Через 30 секунд - все еще в кулдауне
            mock_dt.now.return_value = base_time + timedelta(seconds=30)
            assert sm.is_in_cooldown() is True
            
            # Через 120 секунд - кулдаун закончился
            mock_dt.now.return_value = base_time + timedelta(seconds=120)
            assert sm.is_in_cooldown() is False

    def test_atomic_write_file_creation(self, tmp_path):
        """Тестируем создание файла через атомарную запись."""
        state_file = tmp_path / "new_state.json"
        assert not state_file.exists()
        
        sm = StateManager(str(state_file))
        sm.set("test_key", "test_value")
        
        # Файл должен быть создан
        assert state_file.exists()
        
        # Содержимое должно быть корректным JSON
        with open(state_file, 'r') as f:
            data = json.load(f)
        assert data["test_key"] == "test_value"

    def test_corrupted_json_recovery(self, tmp_path):
        """Тестируем восстановление при поврежденном JSON."""
        state_file = tmp_path / "corrupted.json"
        
        # Создаем поврежденный JSON файл
        with open(state_file, 'w') as f:
            f.write("{ invalid json }")
        
        # StateManager должен создать бэкап и загрузить дефолты
        with patch.object(StateManager, '_backup_file') as mock_backup:
            mock_backup.return_value = str(state_file) + ".backup"
            sm = StateManager(str(state_file))
            
            # Проверяем что создан бэкап
            mock_backup.assert_called_once()
            
            # Проверяем что загружены дефолтные значения
            assert sm.get("trading_state") == TradingState.WAITING.value

    def test_trading_state_enum_handling(self, tmp_path):
        """Тестируем работу с enum TradingState."""
        state_file = tmp_path / "trading_state.json"
        sm = StateManager(str(state_file))
        
        # Установка и получение через enum
        sm.set_trading_state(TradingState.IN_POSITION)
        assert sm.get_trading_state() == TradingState.IN_POSITION
        
        # Проверяем что в файле сохраняется строковое значение
        with open(state_file, 'r') as f:
            data = json.load(f)
        assert data["trading_state"] == "in_position"

    def test_position_management(self, tmp_path):
        """Тестируем управление позицией."""
        state_file = tmp_path / "position.json"
        sm = StateManager(str(state_file))
        
        # Изначально позиция неактивна
        assert not sm.is_position_active()
        
        # Устанавливаем позицию
        sm.set("in_position", True)
        sm.set("symbol", "BTC/USDT")
        sm.set("entry_price", 50000.0)
        
        assert sm.is_position_active()
        
        # Получаем информацию о позиции
        pos_info = sm.get_position_info()
        assert pos_info["active"] is True
        assert pos_info["symbol"] == "BTC/USDT"
        assert pos_info["entry_price"] == 50000.0
        
        # Сбрасываем позицию
        sm.reset_position()
        assert not sm.is_position_active()

    def test_statistics_tracking(self, tmp_path):
        """Тестируем отслеживание статистики."""
        state_file = tmp_path / "stats.json"
        sm = StateManager(str(state_file))
        
        # Изначально статистика пустая
        stats = sm.get_statistics()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
        
        # Добавляем несколько сделок
        sm.increment_trade_count()
        sm.add_profit(100.0)  # Прибыльная сделка
        
        sm.increment_trade_count()
        sm.add_profit(-50.0)  # Убыточная сделка
        
        sm.increment_trade_count()
        sm.add_profit(75.0)   # Еще одна прибыльная
        
        # Проверяем статистику
        stats = sm.get_statistics()
        assert stats["total_trades"] == 3
        assert stats["win_trades"] == 2
        assert stats["lose_trades"] == 1
        assert stats["win_rate"] == 66.67
        assert stats["total_profit"] == 125.0

    def test_cooldown_edge_cases(self, tmp_path):
        """Тестируем граничные случаи кулдауна."""
        state_file = tmp_path / "cooldown.json"
        sm = StateManager(str(state_file))
        
        # Кулдаун без параметров (должен быть 60 минут)
        with patch("core.state_manager.datetime") as mock_dt:
            base_time = datetime.now(timezone.utc)
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            sm.start_cooldown()  # Без параметров
            
            # Через 30 минут - еще в кулдауне
            mock_dt.now.return_value = base_time + timedelta(minutes=30)
            assert sm.is_in_cooldown() is True
            
            # Через 61 минуту - кулдаун закончился
            mock_dt.now.return_value = base_time + timedelta(minutes=61)
            assert sm.is_in_cooldown() is False
        
        # Очистка кулдауна
        sm.clear_cooldown()
        assert not sm.is_in_cooldown()

    def test_concurrent_access_simulation(self, tmp_path):
        """Имитация конкурентного доступа."""
        import threading
        import random
        
        state_file = tmp_path / "concurrent.json"
        sm = StateManager(str(state_file))
        
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(10):
                    # Случайные операции
                    if random.choice([True, False]):
                        sm.set(f"worker_{worker_id}_key_{i}", f"value_{i}")
                    else:
                        value = sm.get(f"worker_{worker_id}_key_{i}", "default")
                        results.append(value)
                    time.sleep(0.001)  # Небольшая пауза
            except Exception as e:
                errors.append(e)
        
        # Запускаем несколько потоков
        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Ждем завершения
        for t in threads:
            t.join()
        
        # Не должно быть ошибок
        assert len(errors) == 0

    def test_data_persistence_across_instances(self, tmp_path):
        """Тестируем сохранение данных между экземплярами."""
        state_file = tmp_path / "persistence.json"
        
        # Первый экземпляр
        sm1 = StateManager(str(state_file))
        sm1.set("persistent_key", "persistent_value")
        sm1.set("total_trades", 5)
        sm1.set_trading_state(TradingState.IN_POSITION)
        
        # Создаем второй экземпляр (имитация перезапуска)
        sm2 = StateManager(str(state_file))
        
        # Данные должны сохраниться
        assert sm2.get("persistent_key") == "persistent_value"
        assert sm2.get("total_trades") == 5
        assert sm2.get_trading_state() == TradingState.IN_POSITION

    def test_update_multiple_values(self, tmp_path):
        """Тестируем обновление нескольких значений одновременно."""
        state_file = tmp_path / "update.json"
        sm = StateManager(str(state_file))
        
        # Атомарное обновление нескольких значений
        update_data = {
            "symbol": "ETH/USDT",
            "entry_price": 3000.0,
            "quantity": 1.5,
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        with patch.object(sm, "_atomic_write") as mock_write:
            sm.update(update_data)
            mock_write.assert_called_once()
        
        # Проверяем что все значения установлены
        for key, value in update_data.items():
            assert sm.get(key) == value

    def test_invalid_trading_state_handling(self, tmp_path):
        """Тестируем обработку некорректных состояний торговли."""
        state_file = tmp_path / "invalid_state.json"
        sm = StateManager(str(state_file))
        
        # Устанавливаем некорректное состояние напрямую в файл
        sm.set("trading_state", "invalid_state")
        
        # get_trading_state должно вернуть дефолтное значение
        assert sm.get_trading_state() == TradingState.WAITING

    def test_position_reset_completeness(self, tmp_path):
        """Тестируем полноту сброса позиции."""
        state_file = tmp_path / "reset.json"
        sm = StateManager(str(state_file))
        
        # Устанавливаем все поля позиции
        position_fields = {
            "in_position": True,
            "opening": True,
            "symbol": "BTC/USDT",
            "entry_price": 50000.0,
            "qty_usd": 1000.0,
            "qty_base": 0.02,
            "buy_score": 0.8,
            "ai_score": 0.9,
            "tp_price_pct": 0.02,
            "sl_price_pct": 0.01
        }
        
        for key, value in position_fields.items():
            sm.set(key, value)
        
        # Проверяем что позиция активна
        assert sm.is_position_active()
        
        # Сбрасываем позицию
        sm.reset_position()
        
        # Проверяем что все поля позиции сброшены к дефолтам
        defaults = sm._default_state()
        pos_keys = sm._derive_position_keys()
        
        for key in pos_keys:
            expected = defaults.get(key)
            actual = sm.get(key)
            assert actual == expected, f"Field {key}: expected {expected}, got {actual}"

    def test_file_permissions_error_handling(self, tmp_path):
        """Тестируем обработку ошибок доступа к файлу."""
        state_file = tmp_path / "readonly.json"
        
        # Создаем файл и делаем его только для чтения
        sm = StateManager(str(state_file))
        sm.set("test", "value")
        
        os.chmod(state_file, 0o444)  # Только чтение
        
        try:
            # Попытка записи должна быть обработана gracefully
            sm.set("another_key", "another_value")
            # Если дошли сюда, значит ошибка была обработана
        except Exception as e:
            # Или проверяем что это ожидаемая ошибка
            assert ("Permission denied" in str(e) or "Read-only" in str(e) or 
                    "Erişim engellendi" in str(e) or "WinError 5" in str(e))
        finally:
            # Восстанавливаем права для cleanup
            os.chmod(state_file, 0o644)

    def test_large_data_handling(self, tmp_path):
        """Тестируем работу с большими объемами данных."""
        state_file = tmp_path / "large_data.json"
        sm = StateManager(str(state_file))
        
        # Большой объект данных
        large_data = {
            f"key_{i}": f"value_{i}" * 100 for i in range(1000)
        }
        
        # Должно работать без ошибок
        sm.update(large_data)
        
        # Проверяем что данные сохранились
        for key, value in list(large_data.items())[:10]:  # Проверяем первые 10
            assert sm.get(key) == value

    def test_export_import_state(self, tmp_path):
        """Тестируем экспорт и импорт состояния."""
        state_file = tmp_path / "export_import.json"
        sm = StateManager(str(state_file))
        
        # Устанавливаем некоторые данные
        test_data = {
            "symbol": "BTC/USDT",
            "entry_price": 45000.0,
            "total_trades": 10
        }
        sm.update(test_data)
        
        # Экспортируем состояние
        exported = sm.export_state()
        assert isinstance(exported, dict)
        for key, value in test_data.items():
            assert exported[key] == value
        
        # Создаем новый экземпляр и импортируем
        sm2 = StateManager(str(tmp_path / "import.json"))
        success = sm2.import_state(exported)
        assert success is True
        
        # Проверяем что данные импортировались
        for key, value in test_data.items():
            assert sm2.get(key) == value

    def test_import_invalid_data(self, tmp_path):
        """Тестируем импорт некорректных данных."""
        state_file = tmp_path / "import_invalid.json"
        sm = StateManager(str(state_file))
        
        # Попытка импорта не-словаря
        with pytest.raises(ValueError):
            sm.import_state("not a dict")
        
        # Попытка импорта None
        with pytest.raises(ValueError):
            sm.import_state(None)
        
        # Попытка импорта списка
        with pytest.raises(ValueError):
            sm.import_state([1, 2, 3])

    @pytest.mark.parametrize("cooldown_seconds", [0, 1, 60, 3600, 86400])
    def test_cooldown_various_durations(self, tmp_path, cooldown_seconds):
        """Параметризованный тест различных длительностей кулдауна."""
        state_file = tmp_path / f"cooldown_{cooldown_seconds}.json"
        sm = StateManager(str(state_file))
        
        with patch("core.state_manager.datetime") as mock_dt:
            base_time = datetime.now(timezone.utc)
            mock_dt.now.return_value = base_time
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            
            sm.start_cooldown(seconds=cooldown_seconds)
            
            # Сразу после установки должен быть в кулдауне (если > 0)
            if cooldown_seconds > 0:
                assert sm.is_in_cooldown() is True
            
            # После истечения времени кулдауна
            mock_dt.now.return_value = base_time + timedelta(seconds=cooldown_seconds + 1)
            assert sm.is_in_cooldown() is False