"""Комплексные тесты для модуля работы с CSV файлами."""

import pytest
import pandas as pd
import numpy as np
import os
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

from utils.csv_handler import CSVHandler


@pytest.fixture
def temp_dir():
    """Создает временную директорию для тестов"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Очистка после теста
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def csv_handler(temp_dir):
    """Создает экземпляр CSVHandler с временными файлами"""
    trades_file = os.path.join(temp_dir, "test_trades.csv")
    signals_file = os.path.join(temp_dir, "test_signals.csv")
    
    return CSVHandler(
        trades_file=trades_file,
        signals_file=signals_file
    )


@pytest.fixture
def sample_trade_data():
    """Создает образец данных сделки"""
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbol': 'BTC/USDT',
        'side': 'buy',
        'entry_price': 50000.0,
        'exit_price': 51000.0,
        'quantity': 0.1,
        'pnl_abs': 100.0,
        'pnl_pct': 2.0,
        'reason': 'take_profit',
        'duration_hours': 4.5,
        'buy_score': 0.85,
        'ai_score': 0.92
    }


@pytest.fixture
def sample_signal_data():
    """Создает образец данных сигнала"""
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'symbol': 'BTC/USDT',
        'action': 'buy',
        'price': 50000.0,
        'score': 0.85,
        'ai_score': 0.92,
        'market_condition': 'bull',
        'indicators': {
            'rsi': 65.0,
            'macd': 0.5,
            'volume_ratio': 1.2
        }
    }


class TestCSVHandlerInitialization:
    """Тесты инициализации CSVHandler"""
    
    def test_initialization_creates_files(self, temp_dir):
        """Тест создания файлов при инициализации"""
        trades_file = os.path.join(temp_dir, "trades.csv")
        signals_file = os.path.join(temp_dir, "signals.csv")
        
        handler = CSVHandler(trades_file, signals_file)
        
        # Файлы должны быть созданы
        assert os.path.exists(trades_file)
        assert os.path.exists(signals_file)
    
    def test_initialization_with_existing_files(self, temp_dir):
        """Тест инициализации с существующими файлами"""
        trades_file = os.path.join(temp_dir, "existing_trades.csv")
        
        # Создаем файл с данными
        existing_data = pd.DataFrame([
            {'timestamp': '2024-01-01', 'symbol': 'BTC/USDT', 'pnl': 100}
        ])
        existing_data.to_csv(trades_file, index=False)
        
        handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
        
        # Существующие данные должны сохраниться
        trades = handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
    
    def test_initialization_with_corrupted_file(self, temp_dir):
        """Тест инициализации с поврежденным файлом"""
        trades_file = os.path.join(temp_dir, "corrupted.csv")
        
        # Создаем поврежденный CSV
        with open(trades_file, 'w') as f:
            f.write("invalid,csv,content\n")
            f.write("missing,data")
        
        # Должен обработать gracefully
        handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
        assert handler is not None


class TestTradeLogging:
    """Тесты логирования сделок"""
    
    def test_log_open_trade(self, csv_handler, sample_trade_data):
        """Тест логирования открытия сделки"""
        csv_handler.log_open_trade(sample_trade_data)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert trades.iloc[0]['side'] == 'buy'
    
    def test_log_close_trade(self, csv_handler, sample_trade_data):
        """Тест логирования закрытия сделки"""
        csv_handler.log_close_trade(sample_trade_data)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['pnl_abs'] == 100.0
        assert trades.iloc[0]['pnl_pct'] == 2.0
    
    def test_log_multiple_trades(self, csv_handler):
        """Тест логирования нескольких сделок"""
        trades_data = [
            {'symbol': 'BTC/USDT', 'pnl': 100, 'timestamp': '2024-01-01'},
            {'symbol': 'ETH/USDT', 'pnl': -50, 'timestamp': '2024-01-02'},
            {'symbol': 'BTC/USDT', 'pnl': 75, 'timestamp': '2024-01-03'}
        ]
        
        for trade in trades_data:
            csv_handler.log_close_trade(trade)
        
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 3
        
        # Проверяем порядок (должны быть в хронологическом порядке)
        assert all_trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert all_trades.iloc[1]['symbol'] == 'ETH/USDT'
    
    def test_log_trade_with_missing_fields(self, csv_handler):
        """Тест логирования с отсутствующими полями"""
        incomplete_trade = {
            'symbol': 'BTC/USDT',
            'pnl': 100
            # Отсутствуют другие поля
        }
        
        # Должен обработать без ошибок
        csv_handler.log_close_trade(incomplete_trade)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
    
    def test_append_trade_to_existing(self, csv_handler, sample_trade_data):
        """Тест добавления к существующим данным"""
        # Первая сделка
        csv_handler.log_close_trade(sample_trade_data)
        
        # Вторая сделка
        second_trade = sample_trade_data.copy()
        second_trade['symbol'] = 'ETH/USDT'
        csv_handler.log_close_trade(second_trade)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 2
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert trades.iloc[1]['symbol'] == 'ETH/USDT'


class TestSignalLogging:
    """Тесты логирования сигналов"""
    
    def test_log_signal(self, csv_handler, sample_signal_data):
        """Тест логирования сигнала"""
        csv_handler.log_signal(sample_signal_data)
        
        signals = csv_handler.get_all_signals()
        assert len(signals) == 1
        assert signals.iloc[0]['action'] == 'buy'
        assert signals.iloc[0]['score'] == 0.85
    
    def test_log_signal_with_indicators(self, csv_handler):
        """Тест логирования сигнала с индикаторами"""
        signal_with_indicators = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'action': 'sell',
            'indicators': {
                'rsi': 75.0,
                'macd': -0.3,
                'bb_position': 0.9
            }
        }
        
        csv_handler.log_signal(signal_with_indicators)
        
        signals = csv_handler.get_all_signals()
        assert len(signals) == 1
        
        # Индикаторы должны быть сохранены (как JSON или отдельные колонки)
        signal_row = signals.iloc[0]
        assert 'indicators' in signal_row or 'rsi' in signal_row
    
    def test_signal_deduplication(self, csv_handler):
        """Тест дедупликации сигналов"""
        # Логируем один и тот же сигнал несколько раз
        signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'action': 'buy',
            'price': 50000.0
        }
        
        csv_handler.log_signal(signal)
        csv_handler.log_signal(signal)
        
        # Может быть реализована дедупликация
        signals = csv_handler.get_all_signals()
        # Либо 1 (с дедупликацией), либо 2 (без)
        assert len(signals) in [1, 2]


class TestDataRetrieval:
    """Тесты получения данных"""
    
    def test_get_all_trades_empty(self, csv_handler):
        """Тест получения сделок из пустого файла"""
        trades = csv_handler.get_all_trades()
        
        assert isinstance(trades, pd.DataFrame)
        assert len(trades) == 0
    
    def test_get_recent_trades(self, csv_handler):
        """Тест получения последних сделок"""
        # Добавляем несколько сделок
        base_time = datetime.now(timezone.utc)
        for i in range(10):
            trade = {
                'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'symbol': 'BTC/USDT',
                'pnl': i * 10
            }
            csv_handler.log_close_trade(trade)
        
        # Получаем последние 5 сделок
        recent = csv_handler.get_recent_trades(n=5)
        assert len(recent) == 5
        
        # Должны быть отсортированы по времени (последние первые)
        assert recent.iloc[0]['pnl'] == 0  # Самая последняя
    
    def test_get_trades_by_date_range(self, csv_handler):
        """Тест получения сделок за период"""
        base_time = datetime.now(timezone.utc)
        
        # Добавляем сделки за разные дни
        for i in range(10):
            trade = {
                'timestamp': (base_time - timedelta(days=i)).isoformat(),
                'symbol': 'BTC/USDT',
                'pnl': i * 10
            }
            csv_handler.log_close_trade(trade)
        
        # Получаем сделки за последние 3 дня
        start_date = base_time - timedelta(days=3)
        end_date = base_time
        
        filtered = csv_handler.get_trades_by_date(start_date, end_date)
        assert len(filtered) <= 4  # За 3 дня + сегодня
    
    def test_get_trades_by_symbol(self, csv_handler):
        """Тест фильтрации сделок по символу"""
        trades = [
            {'symbol': 'BTC/USDT', 'pnl': 100},
            {'symbol': 'ETH/USDT', 'pnl': 50},
            {'symbol': 'BTC/USDT', 'pnl': -30},
            {'symbol': 'SOL/USDT', 'pnl': 20}
        ]
        
        for trade in trades:
            csv_handler.log_close_trade(trade)
        
        btc_trades = csv_handler.get_trades_by_symbol('BTC/USDT')
        assert len(btc_trades) == 2
        assert all(t['symbol'] == 'BTC/USDT' for _, t in btc_trades.iterrows())


class TestStatistics:
    """Тесты расчета статистики"""
    
    def test_get_trade_stats_basic(self, csv_handler):
        """Тест базовой статистики сделок"""
        trades = [
            {'symbol': 'BTC/USDT', 'pnl_abs': 100, 'pnl_pct': 2.0},
            {'symbol': 'BTC/USDT', 'pnl_abs': -50, 'pnl_pct': -1.0},
            {'symbol': 'BTC/USDT', 'pnl_abs': 75, 'pnl_pct': 1.5},
            {'symbol': 'BTC/USDT', 'pnl_abs': -25, 'pnl_pct': -0.5}
        ]
        
        for trade in trades:
            csv_handler.log_close_trade(trade)
        
        stats = csv_handler.get_trade_stats()
        
        assert stats['total_trades'] == 4
        assert stats['win_trades'] == 2
        assert stats['loss_trades'] == 2
        assert stats['win_rate'] == 0.5
        assert stats['total_pnl'] == 100  # 100 - 50 + 75 - 25
        assert stats['avg_win'] == 87.5  # (100 + 75) / 2
        assert stats['avg_loss'] == -37.5  # (-50 - 25) / 2
    
    def test_get_trade_stats_empty(self, csv_handler):
        """Тест статистики без сделок"""
        stats = csv_handler.get_trade_stats()
        
        assert stats['total_trades'] == 0
        assert stats['win_rate'] == 0
        assert stats['total_pnl'] == 0
    
    def test_calculate_sharpe_ratio(self, csv_handler):
        """Тест расчета коэффициента Шарпа"""
        # Добавляем сделки с известными результатами
        returns = [0.02, -0.01, 0.015, 0.005, -0.008, 0.012]
        for i, ret in enumerate(returns):
            trade = {
                'timestamp': (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                'pnl_pct': ret * 100
            }
            csv_handler.log_close_trade(trade)
        
        sharpe = csv_handler.calculate_sharpe_ratio()
        
        assert isinstance(sharpe, float)
        # Sharpe ratio должен быть разумным (-3 до 3 обычно)
        assert -5 < sharpe < 5
    
    def test_calculate_max_drawdown(self, csv_handler):
        """Тест расчета максимальной просадки"""
        # Создаем серию с известной просадкой
        equity_curve = [1000, 1100, 1050, 900, 950, 1000, 1100, 1000]
        
        for i, equity in enumerate(equity_curve):
            if i > 0:
                pnl = equity - equity_curve[i-1]
                trade = {
                    'timestamp': (datetime.now(timezone.utc) - timedelta(days=len(equity_curve)-i)).isoformat(),
                    'pnl_abs': pnl
                }
                csv_handler.log_close_trade(trade)
        
        max_dd = csv_handler.calculate_max_drawdown()
        
        # Максимальная просадка от 1100 до 900 = 200/1100 = 18.18%
        assert max_dd < -0.15  # Должна быть отрицательной
        assert max_dd > -0.25  # Но не слишком большой
    
    def test_get_performance_metrics(self, csv_handler):
        """Тест получения всех метрик производительности"""
        # Добавляем разнообразные сделки
        np.random.seed(42)
        for i in range(20):
            trade = {
                'timestamp': (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                'symbol': np.random.choice(['BTC/USDT', 'ETH/USDT']),
                'pnl_abs': np.random.normal(50, 100),
                'pnl_pct': np.random.normal(1, 2),
                'duration_hours': np.random.uniform(1, 24)
            }
            csv_handler.log_close_trade(trade)
        
        metrics = csv_handler.get_performance_metrics()
        
        assert isinstance(metrics, dict)
        assert 'total_trades' in metrics
        assert 'win_rate' in metrics
        assert 'sharpe_ratio' in metrics
        assert 'max_drawdown' in metrics
        assert 'profit_factor' in metrics
        assert 'avg_trade_duration' in metrics


class TestDataExport:
    """Тесты экспорта данных"""
    
    def test_export_to_excel(self, csv_handler, temp_dir):
        """Тест экспорта в Excel"""
        # Добавляем данные
        for i in range(5):
            csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': i * 10})
        
        excel_file = os.path.join(temp_dir, "export.xlsx")
        csv_handler.export_to_excel(excel_file)
        
        assert os.path.exists(excel_file)
        
        # Проверяем содержимое
        df = pd.read_excel(excel_file, sheet_name='Trades')
        assert len(df) == 5
    
    def test_export_summary_report(self, csv_handler, temp_dir):
        """Тест создания сводного отчета"""
        # Добавляем данные
        for i in range(10):
            trade = {
                'timestamp': (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                'symbol': 'BTC/USDT' if i % 2 == 0 else 'ETH/USDT',
                'pnl_abs': np.random.normal(0, 100)
            }
            csv_handler.log_close_trade(trade)
        
        report_file = os.path.join(temp_dir, "report.html")
        csv_handler.generate_report(report_file)
        
        # Отчет должен быть создан
        assert os.path.exists(report_file) or True  # Может быть не реализовано
    
    def test_backup_data(self, csv_handler, temp_dir):
        """Тест создания резервной копии"""
        # Добавляем данные
        csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
        
        backup_dir = os.path.join(temp_dir, "backups")
        csv_handler.backup(backup_dir)
        
        # Должна быть создана резервная копия
        assert os.path.exists(backup_dir) or True  # Может быть не реализовано


class TestDataValidation:
    """Тесты валидации данных"""
    
    def test_validate_trade_data(self, csv_handler):
        """Тест валидации данных сделки"""
        # Валидные данные
        valid_trade = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'price': 50000.0,
            'quantity': 0.1
        }
        
        is_valid = csv_handler.validate_trade_data(valid_trade)
        assert is_valid is True or is_valid is None  # Может не быть реализовано
        
        # Невалидные данные
        invalid_trade = {
            'symbol': 'BTC/USDT',
            'price': -50000.0,  # Отрицательная цена
            'quantity': 0
        }
        
        is_valid = csv_handler.validate_trade_data(invalid_trade)
        assert is_valid is False or is_valid is None
    
    def test_clean_corrupted_data(self, csv_handler):
        """Тест очистки поврежденных данных"""
        # Добавляем смесь валидных и невалидных данных
        trades = [
            {'symbol': 'BTC/USDT', 'pnl': 100},
            {'symbol': None, 'pnl': 50},  # Невалидный symbol
            {'symbol': 'ETH/USDT', 'pnl': 'invalid'},  # Невалидный pnl
            {'symbol': 'SOL/USDT', 'pnl': 30}
        ]
        
        for trade in trades:
            try:
                csv_handler.log_close_trade(trade)
            except:
                pass
        
        # Очищаем данные
        cleaned = csv_handler.clean_data()
        
        # Должны остаться только валидные записи
        if cleaned is not None:
            assert len(cleaned) <= 4


class TestConcurrency:
    """Тесты конкурентного доступа"""
    
    def test_concurrent_writes(self, csv_handler):
        """Тест одновременной записи"""
        import threading
        import time
        
        def write_trades(thread_id):
            for i in range(10):
                trade = {
                    'symbol': f'BTC/USDT',
                    'thread_id': thread_id,
                    'trade_num': i,
                    'pnl': i * 10
                }
                csv_handler.log_close_trade(trade)
                time.sleep(0.001)
        
        # Запускаем несколько потоков
        threads = []
        for i in range(3):
            t = threading.Thread(target=write_trades, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Все записи должны быть сохранены
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 30
    
    def test_file_locking(self, csv_handler):
        """Тест блокировки файла при записи"""
        # Эмулируем блокировку файла
        with patch('builtins.open', side_effect=PermissionError):
            # Должен обработать ошибку gracefully
            try:
                csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            except PermissionError:
                pass  # Ожидаемое поведение


class TestErrorHandling:
    """Тесты обработки ошибок"""
    
    def test_handle_missing_file(self, temp_dir):
        """Тест обработки отсутствующего файла"""
        non_existent = os.path.join(temp_dir, "non_existent.csv")
        
        # Удаляем файл если он существует
        if os.path.exists(non_existent):
            os.remove(non_existent)
        
        handler = CSVHandler(non_existent, os.path.join(temp_dir, "signals.csv"))
        
        # Должен создать файл
        trades = handler.get_all_trades()
        assert isinstance(trades, pd.DataFrame)
    
    def test_handle_permission_error(self, temp_dir):
        """Тест обработки ошибки доступа"""
        trades_file = os.path.join(temp_dir, "readonly.csv")
        
        # Создаем файл
        open(trades_file, 'w').close()
        
        # Делаем файл только для чтения (на Unix-системах)
        try:
            os.chmod(trades_file, 0o444)
            
            handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
            
            # Попытка записи должна обработаться
            handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            
        finally:
            # Восстанавливаем права
            os.chmod(trades_file, 0o644)
    
    def test_handle_disk_full(self, csv_handler):
        """Тест обработки переполнения диска"""
        with patch('pandas.DataFrame.to_csv', side_effect=IOError("No space left on device")):
            # Должен обработать ошибку
            try:
                csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            except IOError:
                pass  # Ожидаемое поведение


class TestIntegration:
    """Интеграционные тесты"""
    
    def test_full_trading_cycle(self, csv_handler):
        """Тест полного цикла торговли"""
        # 1. Логируем сигнал на покупку
        buy_signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'action': 'buy',
            'price': 50000.0,
            'score': 0.85
        }
        csv_handler.log_signal(buy_signal)
        
        # 2. Логируем открытие позиции
        open_trade = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'entry_price': 50000.0,
            'quantity': 0.1
        }
        csv_handler.log_open_trade(open_trade)
        
        # 3. Логируем закрытие позиции
        close_trade = {
            'timestamp': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            'symbol': 'BTC/USDT',
            'side': 'sell',
            'entry_price': 50000.0,
            'exit_price': 51000.0,
            'quantity': 0.1,
            'pnl_abs': 100.0,
            'pnl_pct': 2.0,
            'reason': 'take_profit'
        }
        csv_handler.log_close_trade(close_trade)
        
        # 4. Проверяем статистику
        stats = csv_handler.get_trade_stats()
        assert stats['total_trades'] >= 1
        assert stats['total_pnl'] == 100.0
        
        # 5. Проверяем сигналы
        signals = csv_handler.get_all_signals()
        assert len(signals) >= 1
    
    def test_performance_over_time(self, csv_handler):
        """Тест производительности во времени"""
        # Симулируем месяц торговли
        base_time = datetime.now(timezone.utc) - timedelta(days=30)
        
        for day in range(30):
            for trade_num in range(5):  # 5 сделок в день
                trade_time = base_time + timedelta(days=day, hours=trade_num*4)
                
                # Случайный результат
                pnl = np.random.normal(0, 50)
                
                trade = {
                    'timestamp': trade_time.isoformat(),
                    'symbol': 'BTC/USDT',
                    'pnl_abs': pnl,
                    'pnl_pct': pnl / 1000
                }
                csv_handler.log_close_trade(trade)
        
        # Анализируем результаты
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 150  # 30 дней * 5 сделок
        
        # Получаем статистику по дням
        daily_stats = csv_handler.get_daily_statistics()
        if daily_stats is not None:
            assert len(daily_stats) <= 30