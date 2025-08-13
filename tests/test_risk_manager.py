"""Комплексные тесты для модуля управления рисками."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Предполагаемая структура RiskManager
from trading.risk_manager import RiskManager, RiskLimits, PositionSizer


@pytest.fixture
def mock_exchange():
    """Мок биржи для тестирования"""
    exchange = Mock()
    exchange.get_balance.return_value = 1000.0
    exchange.get_last_price.return_value = 50000.0
    exchange.market_min_cost.return_value = 5.0
    exchange.market_min_amount.return_value = 0.0001
    return exchange


@pytest.fixture
def mock_state():
    """Мок состояния для тестирования"""
    state = Mock()
    state.get.return_value = None
    state.set.return_value = None
    state.is_position_active.return_value = False
    return state


@pytest.fixture
def risk_manager(mock_exchange, mock_state):
    """Создает экземпляр RiskManager"""
    return RiskManager(
        exchange=mock_exchange,
        state_manager=mock_state,
        max_position_size=0.1,  # 10% от баланса
        stop_loss_pct=0.02,  # 2% стоп-лосс
        take_profit_pct=0.03,  # 3% тейк-профит
        max_daily_loss=0.05,  # 5% максимальный дневной убыток
        max_open_positions=3
    )


class TestRiskManager:
    """Основные тесты RiskManager"""
    
    def test_initialization(self, risk_manager):
        """Тест инициализации"""
        assert risk_manager.max_position_size == 0.1
        assert risk_manager.stop_loss_pct == 0.02
        assert risk_manager.take_profit_pct == 0.03
        assert risk_manager.max_daily_loss == 0.05
        assert risk_manager.max_open_positions == 3
    
    def test_calculate_position_size_basic(self, risk_manager):
        """Тест базового расчета размера позиции"""
        # При балансе 1000 и макс размере 10%
        size = risk_manager.calculate_position_size(
            balance=1000.0,
            price=50000.0,
            confidence=1.0
        )
        
        assert size > 0
        assert size <= 100.0  # Не больше 10% от баланса
    
    def test_calculate_position_size_with_confidence(self, risk_manager):
        """Тест расчета размера с учетом уверенности"""
        high_conf_size = risk_manager.calculate_position_size(
            balance=1000.0,
            price=50000.0,
            confidence=0.9
        )
        
        low_conf_size = risk_manager.calculate_position_size(
            balance=1000.0,
            price=50000.0,
            confidence=0.3
        )
        
        # Размер должен масштабироваться с уверенностью
        assert high_conf_size > low_conf_size
    
    def test_calculate_position_size_minimum_check(self, risk_manager, mock_exchange):
        """Тест проверки минимального размера позиции"""
        # Очень маленький баланс
        size = risk_manager.calculate_position_size(
            balance=10.0,
            price=50000.0,
            confidence=1.0
        )
        
        # Должен вернуть 0 если меньше минимума биржи
        if size < mock_exchange.market_min_cost():
            assert size == 0
    
    def test_calculate_stop_loss(self, risk_manager):
        """Тест расчета стоп-лосса"""
        entry_price = 50000.0
        
        stop_loss = risk_manager.calculate_stop_loss(
            entry_price=entry_price,
            atr=500.0
        )
        
        # Стоп-лосс должен быть ниже входной цены
        assert stop_loss < entry_price
        
        # Проверяем процентное соотношение
        expected_sl = entry_price * (1 - risk_manager.stop_loss_pct)
        assert abs(stop_loss - expected_sl) < 1.0 or stop_loss == entry_price - 2 * 500.0
    
    def test_calculate_take_profit_levels(self, risk_manager):
        """Тест расчета уровней тейк-профита"""
        entry_price = 50000.0
        
        tp_levels = risk_manager.calculate_take_profit_levels(
            entry_price=entry_price,
            atr=500.0
        )
        
        assert isinstance(tp_levels, (list, tuple))
        assert len(tp_levels) > 0
        
        # Все уровни должны быть выше входной цены
        for tp in tp_levels:
            assert tp > entry_price
        
        # Уровни должны быть отсортированы по возрастанию
        assert tp_levels == sorted(tp_levels)
    
    def test_check_daily_loss_limit(self, risk_manager):
        """Тест проверки дневного лимита убытков"""
        # Симулируем дневные потери
        risk_manager.daily_pnl = -30.0  # 3% убыток
        
        # Не должен превышать лимит
        assert risk_manager.check_daily_loss_limit() is True
        
        # Превышаем лимит
        risk_manager.daily_pnl = -60.0  # 6% убыток
        assert risk_manager.check_daily_loss_limit() is False
    
    def test_check_position_limits(self, risk_manager, mock_state):
        """Тест проверки лимитов позиций"""
        # Нет открытых позиций
        mock_state.get.return_value = 0
        assert risk_manager.check_position_limits() is True
        
        # Максимум позиций
        mock_state.get.return_value = 3
        assert risk_manager.check_position_limits() is False
    
    def test_validate_trade_basic(self, risk_manager):
        """Тест базовой валидации сделки"""
        is_valid = risk_manager.validate_trade(
            symbol="BTC/USDT",
            side="buy",
            amount=0.002,
            price=50000.0
        )
        
        assert isinstance(is_valid, bool)
    
    def test_validate_trade_insufficient_balance(self, risk_manager, mock_exchange):
        """Тест валидации при недостаточном балансе"""
        mock_exchange.get_balance.return_value = 10.0  # Маленький баланс
        
        is_valid = risk_manager.validate_trade(
            symbol="BTC/USDT",
            side="buy",
            amount=1.0,  # Большой объем
            price=50000.0
        )
        
        assert is_valid is False
    
    def test_update_daily_pnl(self, risk_manager):
        """Тест обновления дневного PnL"""
        risk_manager.update_daily_pnl(50.0)  # Прибыль
        assert risk_manager.daily_pnl == 50.0
        
        risk_manager.update_daily_pnl(-30.0)  # Убыток
        assert risk_manager.daily_pnl == 20.0  # Суммарно
    
    def test_reset_daily_stats(self, risk_manager):
        """Тест сброса дневной статистики"""
        risk_manager.daily_pnl = -100.0
        risk_manager.daily_trades = 5
        
        risk_manager.reset_daily_stats()
        
        assert risk_manager.daily_pnl == 0.0
        assert risk_manager.daily_trades == 0
    
    def test_get_risk_metrics(self, risk_manager):
        """Тест получения метрик риска"""
        metrics = risk_manager.get_risk_metrics()
        
        assert isinstance(metrics, dict)
        assert "daily_pnl" in metrics
        assert "daily_trades" in metrics
        assert "current_risk" in metrics
        assert "max_position_size" in metrics
    
    def test_adjust_for_volatility(self, risk_manager):
        """Тест корректировки на волатильность"""
        # Низкая волатильность
        size_low_vol = risk_manager.adjust_for_volatility(
            base_size=100.0,
            volatility=0.01  # 1%
        )
        
        # Высокая волатильность
        size_high_vol = risk_manager.adjust_for_volatility(
            base_size=100.0,
            volatility=0.05  # 5%
        )
        
        # При высокой волатильности размер должен быть меньше
        assert size_high_vol < size_low_vol
    
    def test_kelly_criterion(self, risk_manager):
        """Тест критерия Келли для размера позиции"""
        # Положительное математическое ожидание
        kelly_size = risk_manager.kelly_criterion(
            win_rate=0.6,
            avg_win=100.0,
            avg_loss=50.0
        )
        
        assert kelly_size > 0
        assert kelly_size <= 1.0  # Не больше 100%
        
        # Отрицательное математическое ожидание
        kelly_negative = risk_manager.kelly_criterion(
            win_rate=0.3,
            avg_win=50.0,
            avg_loss=100.0
        )
        
        assert kelly_negative == 0  # Не торговать


class TestPositionSizer:
    """Тесты для PositionSizer"""
    
    @pytest.fixture
    def position_sizer(self):
        """Создает экземпляр PositionSizer"""
        return PositionSizer(
            max_risk_per_trade=0.02,
            max_position_pct=0.1,
            min_position_size=10.0
        )
    
    def test_fixed_risk_sizing(self, position_sizer):
        """Тест фиксированного риска на сделку"""
        size = position_sizer.fixed_risk_size(
            balance=10000.0,
            stop_loss_pct=0.02
        )
        
        # Риск = 2% от 10000 = 200
        # При стоп-лоссе 2%, размер = 200 / 0.02 = 10000
        # Но ограничен max_position_pct = 10% = 1000
        assert size <= 1000.0
    
    def test_volatility_adjusted_sizing(self, position_sizer):
        """Тест размера с учетом волатильности"""
        base_size = 1000.0
        
        # ATR sizing
        atr_size = position_sizer.atr_based_size(
            balance=10000.0,
            atr=100.0,
            price=50000.0
        )
        
        assert atr_size > 0
        assert atr_size <= 1000.0  # Не больше лимита
    
    def test_dynamic_position_sizing(self, position_sizer):
        """Тест динамического размера позиции"""
        # При высоком win rate
        size_winning = position_sizer.dynamic_size(
            balance=10000.0,
            recent_win_rate=0.7,
            market_conditions="bull"
        )
        
        # При низком win rate
        size_losing = position_sizer.dynamic_size(
            balance=10000.0,
            recent_win_rate=0.3,
            market_conditions="bear"
        )
        
        assert size_winning > size_losing
    
    def test_martingale_sizing(self, position_sizer):
        """Тест мартингейл размера (антипаттерн, но для полноты)"""
        # После убытка
        size_after_loss = position_sizer.martingale_size(
            base_size=100.0,
            consecutive_losses=2,
            max_multiplier=4.0
        )
        
        assert size_after_loss > 100.0
        assert size_after_loss <= 400.0  # Не больше макс множителя
    
    def test_anti_martingale_sizing(self, position_sizer):
        """Тест анти-мартингейл (увеличение после выигрыша)"""
        size_after_wins = position_sizer.anti_martingale_size(
            base_size=100.0,
            consecutive_wins=3,
            increment_pct=0.1
        )
        
        assert size_after_wins > 100.0


class TestRiskLimits:
    """Тесты для RiskLimits"""
    
    @pytest.fixture
    def risk_limits(self):
        """Создает экземпляр RiskLimits"""
        return RiskLimits(
            max_drawdown=0.2,
            max_daily_loss=0.05,
            max_consecutive_losses=5,
            max_position_correlation=0.7
        )
    
    def test_check_drawdown(self, risk_limits):
        """Тест проверки просадки"""
        # В пределах лимита
        assert risk_limits.check_drawdown(current_dd=0.15) is True
        
        # Превышение лимита
        assert risk_limits.check_drawdown(current_dd=0.25) is False
    
    def test_check_consecutive_losses(self, risk_limits):
        """Тест проверки последовательных убытков"""
        # В пределах лимита
        assert risk_limits.check_consecutive_losses(losses=3) is True
        
        # Превышение лимита
        assert risk_limits.check_consecutive_losses(losses=6) is False
    
    def test_check_correlation(self, risk_limits):
        """Тест проверки корреляции позиций"""
        positions = [
            {"symbol": "BTC/USDT", "correlation": 1.0},
            {"symbol": "ETH/USDT", "correlation": 0.8}
        ]
        
        # Высокая корреляция
        assert risk_limits.check_correlation(positions) is False
        
        positions[1]["correlation"] = 0.3
        # Низкая корреляция
        assert risk_limits.check_correlation(positions) is True
    
    def test_update_metrics(self, risk_limits):
        """Тест обновления метрик"""
        risk_limits.update_metrics(
            trade_result="loss",
            pnl=-50.0,
            drawdown=0.1
        )
        
        assert risk_limits.current_consecutive_losses == 1
        assert risk_limits.current_drawdown == 0.1


class TestRiskManagerIntegration:
    """Интеграционные тесты"""
    
    def test_full_trade_cycle(self, risk_manager, mock_exchange, mock_state):
        """Тест полного цикла сделки"""
        # 1. Проверка возможности открытия
        can_open = risk_manager.can_open_position()
        assert isinstance(can_open, bool)
        
        if can_open:
            # 2. Расчет размера позиции
            size = risk_manager.calculate_position_size(
                balance=1000.0,
                price=50000.0,
                confidence=0.7
            )
            assert size > 0
            
            # 3. Расчет уровней риска
            sl = risk_manager.calculate_stop_loss(50000.0, 500.0)
            tp = risk_manager.calculate_take_profit_levels(50000.0, 500.0)
            
            assert sl < 50000.0
            assert all(t > 50000.0 for t in tp)
            
            # 4. Валидация сделки
            is_valid = risk_manager.validate_trade(
                symbol="BTC/USDT",
                side="buy",
                amount=size/50000.0,
                price=50000.0
            )
            assert isinstance(is_valid, bool)
    
    def test_risk_adjustment_market_conditions(self, risk_manager):
        """Тест корректировки риска под рыночные условия"""
        # Bull market
        bull_size = risk_manager.adjust_for_market(
            base_size=100.0,
            market_condition="bull",
            volatility=0.02
        )
        
        # Bear market
        bear_size = risk_manager.adjust_for_market(
            base_size=100.0,
            market_condition="bear",
            volatility=0.02
        )
        
        # В медвежьем рынке размер должен быть меньше
        assert bear_size < bull_size
    
    def test_emergency_stop(self, risk_manager):
        """Тест экстренной остановки торговли"""
        # Симулируем критические условия
        risk_manager.daily_pnl = -100.0  # Большой убыток
        risk_manager.consecutive_losses = 10
        
        should_stop = risk_manager.check_emergency_stop()
        assert should_stop is True
        
        # После экстренной остановки
        assert risk_manager.is_trading_allowed() is False
    
    @patch('utils.csv_handler.CSVHandler.get_recent_trades')
    def test_performance_based_sizing(self, mock_trades, risk_manager):
        """Тест размера на основе производительности"""
        # Мокаем историю сделок
        mock_trades.return_value = pd.DataFrame({
            'pnl': [50, -20, 30, -10, 40],
            'win': [True, False, True, False, True]
        })
        
        # Размер должен учитывать историю
        size = risk_manager.performance_adjusted_size(
            base_size=100.0,
            lookback_trades=5
        )
        
        # При положительной истории размер может увеличиться
        assert size > 0
    
    def test_multi_timeframe_risk(self, risk_manager):
        """Тест риска на нескольких таймфреймах"""
        # Краткосрочный риск
        short_term_ok = risk_manager.check_timeframe_risk(
            timeframe="5m",
            volatility=0.05
        )
        
        # Долгосрочный риск
        long_term_ok = risk_manager.check_timeframe_risk(
            timeframe="1d",
            volatility=0.02
        )
        
        # Оба должны пройти для открытия позиции
        can_trade = short_term_ok and long_term_ok
        assert isinstance(can_trade, bool)


class TestRiskManagerEdgeCases:
    """Тесты граничных случаев"""
    
    def test_zero_balance(self, risk_manager, mock_exchange):
        """Тест с нулевым балансом"""
        mock_exchange.get_balance.return_value = 0.0
        
        size = risk_manager.calculate_position_size(
            balance=0.0,
            price=50000.0,
            confidence=1.0
        )
        
        assert size == 0
    
    def test_extreme_volatility(self, risk_manager):
        """Тест с экстремальной волатильностью"""
        size = risk_manager.adjust_for_volatility(
            base_size=100.0,
            volatility=0.5  # 50% волатильность
        )
        
        # Должен значительно уменьшить размер
        assert size < 20.0  # Меньше 20% от базового
    
    def test_negative_pnl_recovery(self, risk_manager):
        """Тест восстановления после убытков"""
        risk_manager.daily_pnl = -100.0
        risk_manager.consecutive_losses = 5
        
        # Режим восстановления
        recovery_size = risk_manager.recovery_mode_size(
            base_size=100.0
        )
        
        # В режиме восстановления размер должен быть меньше
        assert recovery_size < 100.0
    
    def test_correlation_with_empty_positions(self, risk_manager):
        """Тест корреляции без открытых позиций"""
        correlation = risk_manager.check_position_correlation(
            new_symbol="BTC/USDT",
            existing_positions=[]
        )
        
        # Без позиций корреляция не проблема
        assert correlation is True
    
    def test_invalid_risk_parameters(self):
        """Тест с невалидными параметрами риска"""
        with pytest.raises((ValueError, AssertionError)):
            RiskManager(
                exchange=Mock(),
                state_manager=Mock(),
                max_position_size=1.5,  # Больше 100%
                stop_loss_pct=-0.02,  # Отрицательный стоп-лосс
                take_profit_pct=0.03
            )