"""Тесты для SimplePositionManager."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from trading.position_manager import SimplePositionManager
from trading.exchange_client import APIException

def make_state_mock(initial):
    """Создаём мок, имитирующий StateManager на основе словаря"""
    state = MagicMock()
    data = dict(initial)
    
    def get_side_effect(key, default=None):
        return data.get(key, default)
    
    def set_side_effect(key, value):
        data[key] = value
    
    state.get.side_effect = get_side_effect
    state.set.side_effect = set_side_effect
    return state, data

class TestSimplePositionManager:
    """Тесты менеджера позиций для торгового бота"""
    
    def test_open_long_updates_state(self):
        """Проверяем, что открытие лонга обновляет состояние"""
        exchange = MagicMock()
        exchange.market_min_cost.return_value = 0
        exchange.create_market_buy_order.return_value = {"id": "test_123"}
        
        state, data = make_state_mock({"in_position": False, "opening": False})
        pm = SimplePositionManager(exchange, state)
        
        result = pm.open_long("BTC/USDT", 10.0, 100.0)
        
        assert result is not None
        assert data["in_position"] is True
        assert data["opening"] is False
        assert data["symbol"] == "BTC/USDT"
        assert data["entry_price"] == 100.0

    @patch("trading.position_manager.CSVHandler.log_close_trade")
    def test_close_all_resets_state(self, mock_log):
        """Проверяем, что закрытие позиции сбрасывает состояние и запускает охлаждение"""
        exchange = MagicMock()
        exchange.create_market_sell_order.return_value = {"id": "sell_123"}
        
        now = datetime.now(timezone.utc).isoformat()
        initial = {
            "in_position": True,
            "opening": False,
            "entry_price": 100.0,
            "qty_base": 1.0,
            "qty_usd": 100.0,
            "buy_score": None,
            "ai_score": None,
            "entry_ts": now,
        }
        state, data = make_state_mock(initial)
        pm = SimplePositionManager(exchange, state)
        
        result = pm.close_all("BTC/USDT", 110.0, "take_profit")
        
        state.reset_position.assert_called_once()
        state.start_cooldown.assert_called_once()
        assert result["side"] == "sell"

    def test_prevent_double_position_opening(self):
        """КРИТИЧНО: предотвращение открытия двойной позиции"""
        exchange = MagicMock()
        state, data = make_state_mock({"in_position": True})  # Уже в позиции
        
        pm = SimplePositionManager(exchange, state)
        result = pm.open_long("BTC/USDT", 10.0, 100.0)
        
        # Не должна открыться
        assert result is None
        exchange.create_market_buy_order.assert_not_called()

    def test_exchange_api_error_handling(self):
        """Тест обработки ошибок API биржи"""
        exchange = MagicMock()
        exchange.market_min_cost.return_value = 0
        exchange.create_market_buy_order.side_effect = APIException("API Error")
        
        state, data = make_state_mock({"in_position": False, "opening": False})
        pm = SimplePositionManager(exchange, state)
        
        result = pm.open_long("BTC/USDT", 10.0, 100.0)
        
        # При ошибке API позиция не должна открыться
        assert result is None
        assert data["opening"] is False  # Флаг сброшен
        assert data["in_position"] is False

    @patch("trading.position_manager.CSVHandler.log_close_trade")
    def test_pnl_calculation_profit(self, mock_log):
        """Тест расчета прибыли при закрытии позиции"""
        exchange = MagicMock()
        exchange.create_market_sell_order.return_value = {"id": "sell_123"}
        
        initial = {
            "in_position": True,
            "entry_price": 100.0,
            "qty_base": 0.1,  # 0.1 BTC
            "qty_usd": 10.0,
            "entry_ts": datetime.now(timezone.utc).isoformat(),
        }
        state, data = make_state_mock(initial)
        pm = SimplePositionManager(exchange, state)
        
        # Закрываем по цене 110 (+10%)
        result = pm.close_all("BTC/USDT", 110.0, "take_profit")
        
        # Проверяем логирование PnL
        mock_log.assert_called_once()
        log_data = mock_log.call_args[0][0]
        
        assert log_data["pnl_pct"] == 10.0  # 10% прибыль
        assert log_data["pnl_abs"] == 1.0   # 0.1 * (110-100)

    @patch("trading.position_manager.CSVHandler.log_close_trade")
    def test_pnl_calculation_loss(self, mock_log):
        """Тест расчета убытка при закрытии позиции"""
        exchange = MagicMock()
        exchange.create_market_sell_order.return_value = {"id": "sell_123"}
        
        initial = {
            "in_position": True,
            "entry_price": 100.0,
            "qty_base": 0.1,
            "qty_usd": 10.0,
            "entry_ts": datetime.now(timezone.utc).isoformat(),
        }
        state, data = make_state_mock(initial)
        pm = SimplePositionManager(exchange, state)
        
        # Закрываем по цене 90 (-10%)
        result = pm.close_all("BTC/USDT", 90.0, "stop_loss")
        
        mock_log.assert_called_once()
        log_data = mock_log.call_args[0][0]
        
        assert log_data["pnl_pct"] == -10.0  # 10% убыток
        assert log_data["pnl_abs"] == -1.0   # 0.1 * (90-100)

    def test_position_management_stop_loss_trigger(self):
        """Тест автоматического срабатывания стоп-лосса"""
        exchange = MagicMock()
        exchange.create_market_sell_order.return_value = {"id": "sl_123"}
        
        initial = {
            "in_position": True,
            "entry_price": 100.0,
            "sl_atr": 95.0,  # Стоп-лосс на 95
            "qty_base": 0.1,
            "last_manage_check": datetime.now(timezone.utc).isoformat(),
        }
        state, data = make_state_mock(initial)
        
        # Мокируем _is_position_active()
        pm = SimplePositionManager(exchange, state)
        pm._is_position_active = lambda: True
        
        # Цена упала ниже стоп-лосса
        pm.manage("BTC/USDT", current_price=94.0, atr=2.0)
        
        # Должна сработать продажа
        exchange.create_market_sell_order.assert_called_once()
        state.reset_position.assert_called_once()

    def test_position_management_take_profit_trigger(self):
        """Тест срабатывания тейк-профита"""
        exchange = MagicMock()
        
        initial = {
            "in_position": True,
            "entry_price": 100.0,
            "tp1_atr": 105.0,  # Тейк-профит на 105
            "partial_taken": False,
            "last_manage_check": datetime.now(timezone.utc).isoformat(),
        }
        state, data = make_state_mock(initial)
        
        pm = SimplePositionManager(exchange, state)
        pm._is_position_active = lambda: True
        
        # Цена достигла тейк-профита
        pm.manage("BTC/USDT", current_price=106.0, atr=2.0)
        
        # Должна обновиться информация о частичном закрытии
        assert data["partial_taken"] is True

    def test_safe_mode_position_operations(self):
        """Тест операций в безопасном режиме (paper trading)"""
        with patch('config.settings.TradingConfig') as mock_config:
            mock_config_instance = MagicMock()
            mock_config_instance.SAFE_MODE = True
            mock_config.return_value = mock_config_instance
            
            exchange = MagicMock()
            state, data = make_state_mock({"in_position": False, "opening": False})
            
            pm = SimplePositionManager(exchange, state)
            result = pm.open_long("BTC/USDT", 10.0, 100.0)
            
            # В SAFE_MODE должны создаваться симулированные ордера
            assert result is not None
            assert "paper" in result or "sim" in str(result.get("id", ""))