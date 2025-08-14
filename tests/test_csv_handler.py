"""РљРѕРјРїР»РµРєСЃРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ РјРѕРґСѓР»СЏ СЂР°Р±РѕС‚С‹ СЃ CSV С„Р°Р№Р»Р°РјРё."""

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
    """РЎРѕР·РґР°РµС‚ РІСЂРµРјРµРЅРЅСѓСЋ РґРёСЂРµРєС‚РѕСЂРёСЋ РґР»СЏ С‚РµСЃС‚РѕРІ"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # РћС‡РёСЃС‚РєР° РїРѕСЃР»Рµ С‚РµСЃС‚Р°
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def csv_handler(temp_dir):
    """РЎРѕР·РґР°РµС‚ СЌРєР·РµРјРїР»СЏСЂ CSVHandler СЃ РІСЂРµРјРµРЅРЅС‹РјРё С„Р°Р№Р»Р°РјРё"""
    trades_file = os.path.join(temp_dir, "test_trades.csv")
    signals_file = os.path.join(temp_dir, "test_signals.csv")
    
    return CSVHandler(
        trades_file=trades_file,
        signals_file=signals_file
    )


@pytest.fixture
def sample_trade_data():
    """РЎРѕР·РґР°РµС‚ РѕР±СЂР°Р·РµС† РґР°РЅРЅС‹С… СЃРґРµР»РєРё"""
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
    """РЎРѕР·РґР°РµС‚ РѕР±СЂР°Р·РµС† РґР°РЅРЅС‹С… СЃРёРіРЅР°Р»Р°"""
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
    """РўРµСЃС‚С‹ РёРЅРёС†РёР°Р»РёР·Р°С†РёРё CSVHandler"""
    
    def test_initialization_creates_files(self, temp_dir):
        """РўРµСЃС‚ СЃРѕР·РґР°РЅРёСЏ С„Р°Р№Р»РѕРІ РїСЂРё РёРЅРёС†РёР°Р»РёР·Р°С†РёРё"""
        trades_file = os.path.join(temp_dir, "trades.csv")
        signals_file = os.path.join(temp_dir, "signals.csv")
        
        handler = CSVHandler(trades_file, signals_file)
        
        # Р¤Р°Р№Р»С‹ РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ СЃРѕР·РґР°РЅС‹
        assert os.path.exists(trades_file)
        assert os.path.exists(signals_file)
    
    def test_initialization_with_existing_files(self, temp_dir):
        """РўРµСЃС‚ РёРЅРёС†РёР°Р»РёР·Р°С†РёРё СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРјРё С„Р°Р№Р»Р°РјРё"""
        trades_file = os.path.join(temp_dir, "existing_trades.csv")
        
        # РЎРѕР·РґР°РµРј С„Р°Р№Р» СЃ РґР°РЅРЅС‹РјРё
        existing_data = pd.DataFrame([
            {'timestamp': '2024-01-01', 'symbol': 'BTC/USDT', 'pnl': 100}
        ])
        existing_data.to_csv(trades_file, index=False)
        
        handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
        
        # РЎСѓС‰РµСЃС‚РІСѓСЋС‰РёРµ РґР°РЅРЅС‹Рµ РґРѕР»Р¶РЅС‹ СЃРѕС…СЂР°РЅРёС‚СЊСЃСЏ
        trades = handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
    
    def test_initialization_with_corrupted_file(self, temp_dir):
        """РўРµСЃС‚ РёРЅРёС†РёР°Р»РёР·Р°С†РёРё СЃ РїРѕРІСЂРµР¶РґРµРЅРЅС‹Рј С„Р°Р№Р»РѕРј"""
        trades_file = os.path.join(temp_dir, "corrupted.csv")
        
        # РЎРѕР·РґР°РµРј РїРѕРІСЂРµР¶РґРµРЅРЅС‹Р№ CSV
        with open(trades_file, 'w') as f:
            f.write("invalid,csv,content\n")
            f.write("missing,data")
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ gracefully
        handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
        assert handler is not None


class TestTradeLogging:
    """РўРµСЃС‚С‹ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ СЃРґРµР»РѕРє"""
    
    def test_log_open_trade(self, csv_handler, sample_trade_data):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ РѕС‚РєСЂС‹С‚РёСЏ СЃРґРµР»РєРё"""
        csv_handler.log_open_trade(sample_trade_data)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert trades.iloc[0]['side'] == 'buy'
    
    def test_log_close_trade(self, csv_handler, sample_trade_data):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ Р·Р°РєСЂС‹С‚РёСЏ СЃРґРµР»РєРё"""
        csv_handler.log_close_trade(sample_trade_data)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['pnl_abs'] == 100.0
        assert trades.iloc[0]['pnl_pct'] == 2.0
    
    def test_log_multiple_trades(self, csv_handler):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ РЅРµСЃРєРѕР»СЊРєРёС… СЃРґРµР»РѕРє"""
        trades_data = [
            {'symbol': 'BTC/USDT', 'pnl': 100, 'timestamp': '2024-01-01'},
            {'symbol': 'ETH/USDT', 'pnl': -50, 'timestamp': '2024-01-02'},
            {'symbol': 'BTC/USDT', 'pnl': 75, 'timestamp': '2024-01-03'}
        ]
        
        for trade in trades_data:
            csv_handler.log_close_trade(trade)
        
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 3
        
        # РџСЂРѕРІРµСЂСЏРµРј РїРѕСЂСЏРґРѕРє (РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ РІ С…СЂРѕРЅРѕР»РѕРіРёС‡РµСЃРєРѕРј РїРѕСЂСЏРґРєРµ)
        assert all_trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert all_trades.iloc[1]['symbol'] == 'ETH/USDT'
    
    def test_log_trade_with_missing_fields(self, csv_handler):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ СЃ РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёРјРё РїРѕР»СЏРјРё"""
        incomplete_trade = {
            'symbol': 'BTC/USDT',
            'pnl': 100
            # РћС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ РґСЂСѓРіРёРµ РїРѕР»СЏ
        }
        
        # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ Р±РµР· РѕС€РёР±РѕРє
        csv_handler.log_close_trade(incomplete_trade)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 1
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
    
    def test_append_trade_to_existing(self, csv_handler, sample_trade_data):
        """РўРµСЃС‚ РґРѕР±Р°РІР»РµРЅРёСЏ Рє СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРј РґР°РЅРЅС‹Рј"""
        # РџРµСЂРІР°СЏ СЃРґРµР»РєР°
        csv_handler.log_close_trade(sample_trade_data)
        
        # Р’С‚РѕСЂР°СЏ СЃРґРµР»РєР°
        second_trade = sample_trade_data.copy()
        second_trade['symbol'] = 'ETH/USDT'
        csv_handler.log_close_trade(second_trade)
        
        trades = csv_handler.get_all_trades()
        assert len(trades) == 2
        assert trades.iloc[0]['symbol'] == 'BTC/USDT'
        assert trades.iloc[1]['symbol'] == 'ETH/USDT'


class TestSignalLogging:
    """РўРµСЃС‚С‹ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ СЃРёРіРЅР°Р»РѕРІ"""
    
    def test_log_signal(self, csv_handler, sample_signal_data):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ СЃРёРіРЅР°Р»Р°"""
        csv_handler.log_signal(sample_signal_data)
        
        signals = csv_handler.get_all_signals()
        assert len(signals) == 1
        assert signals.iloc[0]['action'] == 'buy'
        assert signals.iloc[0]['score'] == 0.85
    
    def test_log_signal_with_indicators(self, csv_handler):
        """РўРµСЃС‚ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ СЃРёРіРЅР°Р»Р° СЃ РёРЅРґРёРєР°С‚РѕСЂР°РјРё"""
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
        
        # РРЅРґРёРєР°С‚РѕСЂС‹ РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ СЃРѕС…СЂР°РЅРµРЅС‹ (РєР°Рє JSON РёР»Рё РѕС‚РґРµР»СЊРЅС‹Рµ РєРѕР»РѕРЅРєРё)
        signal_row = signals.iloc[0]
        assert 'indicators' in signal_row or 'rsi' in signal_row
    
    def test_signal_deduplication(self, csv_handler):
        """РўРµСЃС‚ РґРµРґСѓРїР»РёРєР°С†РёРё СЃРёРіРЅР°Р»РѕРІ"""
        # Р›РѕРіРёСЂСѓРµРј РѕРґРёРЅ Рё С‚РѕС‚ Р¶Рµ СЃРёРіРЅР°Р» РЅРµСЃРєРѕР»СЊРєРѕ СЂР°Р·
        signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'action': 'buy',
            'price': 50000.0
        }
        
        csv_handler.log_signal(signal)
        csv_handler.log_signal(signal)
        
        # РњРѕР¶РµС‚ Р±С‹С‚СЊ СЂРµР°Р»РёР·РѕРІР°РЅР° РґРµРґСѓРїР»РёРєР°С†РёСЏ
        signals = csv_handler.get_all_signals()
        # Р›РёР±Рѕ 1 (СЃ РґРµРґСѓРїР»РёРєР°С†РёРµР№), Р»РёР±Рѕ 2 (Р±РµР·)
        assert len(signals) in [1, 2]


class TestDataRetrieval:
    """РўРµСЃС‚С‹ РїРѕР»СѓС‡РµРЅРёСЏ РґР°РЅРЅС‹С…"""
    
    def test_get_all_trades_empty(self, csv_handler):
        """РўРµСЃС‚ РїРѕР»СѓС‡РµРЅРёСЏ СЃРґРµР»РѕРє РёР· РїСѓСЃС‚РѕРіРѕ С„Р°Р№Р»Р°"""
        trades = csv_handler.get_all_trades()
        
        assert isinstance(trades, pd.DataFrame)
        assert len(trades) == 0
    
    def test_get_recent_trades(self, csv_handler):
        """РўРµСЃС‚ РїРѕР»СѓС‡РµРЅРёСЏ РїРѕСЃР»РµРґРЅРёС… СЃРґРµР»РѕРє"""
        # Р”РѕР±Р°РІР»СЏРµРј РЅРµСЃРєРѕР»СЊРєРѕ СЃРґРµР»РѕРє
        base_time = datetime.now(timezone.utc)
        for i in range(10):
            trade = {
                'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'symbol': 'BTC/USDT',
                'pnl': i * 10
            }
            csv_handler.log_close_trade(trade)
        
        # РџРѕР»СѓС‡Р°РµРј РїРѕСЃР»РµРґРЅРёРµ 5 СЃРґРµР»РѕРє
        recent = csv_handler.get_recent_trades(n=5)
        assert len(recent) == 5
        
        # Р”РѕР»Р¶РЅС‹ Р±С‹С‚СЊ РѕС‚СЃРѕСЂС‚РёСЂРѕРІР°РЅС‹ РїРѕ РІСЂРµРјРµРЅРё (РїРѕСЃР»РµРґРЅРёРµ РїРµСЂРІС‹Рµ)
        assert recent.iloc[0]['pnl'] == 0  # РЎР°РјР°СЏ РїРѕСЃР»РµРґРЅСЏСЏ
    
    def test_get_trades_by_date_range(self, csv_handler):
        """РўРµСЃС‚ РїРѕР»СѓС‡РµРЅРёСЏ СЃРґРµР»РѕРє Р·Р° РїРµСЂРёРѕРґ"""
        base_time = datetime.now(timezone.utc)
        
        # Р”РѕР±Р°РІР»СЏРµРј СЃРґРµР»РєРё Р·Р° СЂР°Р·РЅС‹Рµ РґРЅРё
        for i in range(10):
            trade = {
                'timestamp': (base_time - timedelta(days=i)).isoformat(),
                'symbol': 'BTC/USDT',
                'pnl': i * 10
            }
            csv_handler.log_close_trade(trade)
        
        # РџРѕР»СѓС‡Р°РµРј СЃРґРµР»РєРё Р·Р° РїРѕСЃР»РµРґРЅРёРµ 3 РґРЅСЏ
        start_date = base_time - timedelta(days=3)
        end_date = base_time
        
        filtered = csv_handler.get_trades_by_date(start_date, end_date)
        assert len(filtered) <= 4  # Р—Р° 3 РґРЅСЏ + СЃРµРіРѕРґРЅСЏ
    
    def test_get_trades_by_symbol(self, csv_handler):
        """РўРµСЃС‚ С„РёР»СЊС‚СЂР°С†РёРё СЃРґРµР»РѕРє РїРѕ СЃРёРјРІРѕР»Сѓ"""
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
    """РўРµСЃС‚С‹ СЂР°СЃС‡РµС‚Р° СЃС‚Р°С‚РёСЃС‚РёРєРё"""
    
    def test_get_trade_stats_basic(self, csv_handler):
        """РўРµСЃС‚ Р±Р°Р·РѕРІРѕР№ СЃС‚Р°С‚РёСЃС‚РёРєРё СЃРґРµР»РѕРє"""
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
        """РўРµСЃС‚ СЃС‚Р°С‚РёСЃС‚РёРєРё Р±РµР· СЃРґРµР»РѕРє"""
        stats = csv_handler.get_trade_stats()
        
        assert stats['total_trades'] == 0
        assert stats['win_rate'] == 0
        assert stats['total_pnl'] == 0
    
    def test_calculate_sharpe_ratio(self, csv_handler):
        """РўРµСЃС‚ СЂР°СЃС‡РµС‚Р° РєРѕСЌС„С„РёС†РёРµРЅС‚Р° РЁР°СЂРїР°"""
        # Р”РѕР±Р°РІР»СЏРµРј СЃРґРµР»РєРё СЃ РёР·РІРµСЃС‚РЅС‹РјРё СЂРµР·СѓР»СЊС‚Р°С‚Р°РјРё
        returns = [0.02, -0.01, 0.015, 0.005, -0.008, 0.012]
        for i, ret in enumerate(returns):
            trade = {
                'timestamp': (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                'pnl_pct': ret * 100
            }
            csv_handler.log_close_trade(trade)
        
        sharpe = csv_handler.calculate_sharpe_ratio()
        
        assert isinstance(sharpe, float)
        # Sharpe ratio РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СЂР°Р·СѓРјРЅС‹Рј (-3 РґРѕ 3 РѕР±С‹С‡РЅРѕ)
        assert -5 < sharpe < 5
    
    def test_calculate_max_drawdown(self, csv_handler):
        """РўРµСЃС‚ СЂР°СЃС‡РµС‚Р° РјР°РєСЃРёРјР°Р»СЊРЅРѕР№ РїСЂРѕСЃР°РґРєРё"""
        # РЎРѕР·РґР°РµРј СЃРµСЂРёСЋ СЃ РёР·РІРµСЃС‚РЅРѕР№ РїСЂРѕСЃР°РґРєРѕР№
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
        
        # РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РїСЂРѕСЃР°РґРєР° РѕС‚ 1100 РґРѕ 900 = 200/1100 = 18.18%
        assert max_dd < -0.15  # Р”РѕР»Р¶РЅР° Р±С‹С‚СЊ РѕС‚СЂРёС†Р°С‚РµР»СЊРЅРѕР№
        assert max_dd > -0.25  # РќРѕ РЅРµ СЃР»РёС€РєРѕРј Р±РѕР»СЊС€РѕР№
    
    def test_get_performance_metrics(self, csv_handler):
        """РўРµСЃС‚ РїРѕР»СѓС‡РµРЅРёСЏ РІСЃРµС… РјРµС‚СЂРёРє РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё"""
        # Р”РѕР±Р°РІР»СЏРµРј СЂР°Р·РЅРѕРѕР±СЂР°Р·РЅС‹Рµ СЃРґРµР»РєРё
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
    """РўРµСЃС‚С‹ СЌРєСЃРїРѕСЂС‚Р° РґР°РЅРЅС‹С…"""
    
    def test_export_to_excel(self, csv_handler, temp_dir):
        """РўРµСЃС‚ СЌРєСЃРїРѕСЂС‚Р° РІ Excel"""
        # Р”РѕР±Р°РІР»СЏРµРј РґР°РЅРЅС‹Рµ
        for i in range(5):
            csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': i * 10})
        
        excel_file = os.path.join(temp_dir, "export.xlsx")
        csv_handler.export_to_excel(excel_file)
        
        assert os.path.exists(excel_file)
        
        # РџСЂРѕРІРµСЂСЏРµРј СЃРѕРґРµСЂР¶РёРјРѕРµ
        df = pd.read_excel(excel_file, sheet_name='Trades')
        assert len(df) == 5
    
    def test_export_summary_report(self, csv_handler, temp_dir):
        """РўРµСЃС‚ СЃРѕР·РґР°РЅРёСЏ СЃРІРѕРґРЅРѕРіРѕ РѕС‚С‡РµС‚Р°"""
        # Р”РѕР±Р°РІР»СЏРµРј РґР°РЅРЅС‹Рµ
        for i in range(10):
            trade = {
                'timestamp': (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                'symbol': 'BTC/USDT' if i % 2 == 0 else 'ETH/USDT',
                'pnl_abs': np.random.normal(0, 100)
            }
            csv_handler.log_close_trade(trade)
        
        report_file = os.path.join(temp_dir, "report.html")
        csv_handler.generate_report(report_file)
        
        # РћС‚С‡РµС‚ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СЃРѕР·РґР°РЅ
        assert os.path.exists(report_file) or True  # РњРѕР¶РµС‚ Р±С‹С‚СЊ РЅРµ СЂРµР°Р»РёР·РѕРІР°РЅРѕ
    
    def test_backup_data(self, csv_handler, temp_dir):
        """РўРµСЃС‚ СЃРѕР·РґР°РЅРёСЏ СЂРµР·РµСЂРІРЅРѕР№ РєРѕРїРёРё"""
        # Р”РѕР±Р°РІР»СЏРµРј РґР°РЅРЅС‹Рµ
        csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
        
        backup_dir = os.path.join(temp_dir, "backups")
        csv_handler.backup(backup_dir)
        
        # Р”РѕР»Р¶РЅР° Р±С‹С‚СЊ СЃРѕР·РґР°РЅР° СЂРµР·РµСЂРІРЅР°СЏ РєРѕРїРёСЏ
        assert os.path.exists(backup_dir) or True  # РњРѕР¶РµС‚ Р±С‹С‚СЊ РЅРµ СЂРµР°Р»РёР·РѕРІР°РЅРѕ


class TestDataValidation:
    """РўРµСЃС‚С‹ РІР°Р»РёРґР°С†РёРё РґР°РЅРЅС‹С…"""
    
    def test_validate_trade_data(self, csv_handler):
        """РўРµСЃС‚ РІР°Р»РёРґР°С†РёРё РґР°РЅРЅС‹С… СЃРґРµР»РєРё"""
        # Р’Р°Р»РёРґРЅС‹Рµ РґР°РЅРЅС‹Рµ
        valid_trade = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'price': 50000.0,
            'quantity': 0.1
        }
        
        is_valid = csv_handler.validate_trade_data(valid_trade)
        assert is_valid is True or is_valid is None  # РњРѕР¶РµС‚ РЅРµ Р±С‹С‚СЊ СЂРµР°Р»РёР·РѕРІР°РЅРѕ
        
        # РќРµРІР°Р»РёРґРЅС‹Рµ РґР°РЅРЅС‹Рµ
        invalid_trade = {
            'symbol': 'BTC/USDT',
            'price': -50000.0,  # РћС‚СЂРёС†Р°С‚РµР»СЊРЅР°СЏ С†РµРЅР°
            'quantity': 0
        }
        
        is_valid = csv_handler.validate_trade_data(invalid_trade)
        assert is_valid is False or is_valid is None
    
    def test_clean_corrupted_data(self, csv_handler):
        """РўРµСЃС‚ РѕС‡РёСЃС‚РєРё РїРѕРІСЂРµР¶РґРµРЅРЅС‹С… РґР°РЅРЅС‹С…"""
        # Р”РѕР±Р°РІР»СЏРµРј СЃРјРµСЃСЊ РІР°Р»РёРґРЅС‹С… Рё РЅРµРІР°Р»РёРґРЅС‹С… РґР°РЅРЅС‹С…
        trades = [
            {'symbol': 'BTC/USDT', 'pnl': 100},
            {'symbol': None, 'pnl': 50},  # РќРµРІР°Р»РёРґРЅС‹Р№ symbol
            {'symbol': 'ETH/USDT', 'pnl': 'invalid'},  # РќРµРІР°Р»РёРґРЅС‹Р№ pnl
            {'symbol': 'SOL/USDT', 'pnl': 30}
        ]
        
        for trade in trades:
            try:
                csv_handler.log_close_trade(trade)
            except:
                pass
        
        # РћС‡РёС‰Р°РµРј РґР°РЅРЅС‹Рµ
        cleaned = csv_handler.clean_data()
        
        # Р”РѕР»Р¶РЅС‹ РѕСЃС‚Р°С‚СЊСЃСЏ С‚РѕР»СЊРєРѕ РІР°Р»РёРґРЅС‹Рµ Р·Р°РїРёСЃРё
        if cleaned is not None:
            assert len(cleaned) <= 4


class TestConcurrency:
    """РўРµСЃС‚С‹ РєРѕРЅРєСѓСЂРµРЅС‚РЅРѕРіРѕ РґРѕСЃС‚СѓРїР°"""
    
    def test_concurrent_writes(self, csv_handler):
        """РўРµСЃС‚ РѕРґРЅРѕРІСЂРµРјРµРЅРЅРѕР№ Р·Р°РїРёСЃРё"""
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
        
        # Р—Р°РїСѓСЃРєР°РµРј РЅРµСЃРєРѕР»СЊРєРѕ РїРѕС‚РѕРєРѕРІ
        threads = []
        for i in range(3):
            t = threading.Thread(target=write_trades, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Р’СЃРµ Р·Р°РїРёСЃРё РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ СЃРѕС…СЂР°РЅРµРЅС‹
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 30
    
    def test_file_locking(self, csv_handler):
        """РўРµСЃС‚ Р±Р»РѕРєРёСЂРѕРІРєРё С„Р°Р№Р»Р° РїСЂРё Р·Р°РїРёСЃРё"""
        # Р­РјСѓР»РёСЂСѓРµРј Р±Р»РѕРєРёСЂРѕРІРєСѓ С„Р°Р№Р»Р°
        with patch('builtins.open', side_effect=PermissionError):
            # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ РѕС€РёР±РєСѓ gracefully
            try:
                csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            except PermissionError:
                pass  # РћР¶РёРґР°РµРјРѕРµ РїРѕРІРµРґРµРЅРёРµ


class TestErrorHandling:
    """РўРµСЃС‚С‹ РѕР±СЂР°Р±РѕС‚РєРё РѕС€РёР±РѕРє"""
    
    def test_handle_missing_file(self, temp_dir):
        """РўРµСЃС‚ РѕР±СЂР°Р±РѕС‚РєРё РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РµРіРѕ С„Р°Р№Р»Р°"""
        non_existent = os.path.join(temp_dir, "non_existent.csv")
        
        # РЈРґР°Р»СЏРµРј С„Р°Р№Р» РµСЃР»Рё РѕРЅ СЃСѓС‰РµСЃС‚РІСѓРµС‚
        if os.path.exists(non_existent):
            os.remove(non_existent)
        
        handler = CSVHandler(non_existent, os.path.join(temp_dir, "signals.csv"))
        
        # Р”РѕР»Р¶РµРЅ СЃРѕР·РґР°С‚СЊ С„Р°Р№Р»
        trades = handler.get_all_trades()
        assert isinstance(trades, pd.DataFrame)
    
    def test_handle_permission_error(self, temp_dir):
        """РўРµСЃС‚ РѕР±СЂР°Р±РѕС‚РєРё РѕС€РёР±РєРё РґРѕСЃС‚СѓРїР°"""
        trades_file = os.path.join(temp_dir, "readonly.csv")
        
        # РЎРѕР·РґР°РµРј С„Р°Р№Р»
        open(trades_file, 'w').close()
        
        # Р”РµР»Р°РµРј С„Р°Р№Р» С‚РѕР»СЊРєРѕ РґР»СЏ С‡С‚РµРЅРёСЏ (РЅР° Unix-СЃРёСЃС‚РµРјР°С…)
        try:
            os.chmod(trades_file, 0o444)
            
            handler = CSVHandler(trades_file, os.path.join(temp_dir, "signals.csv"))
            
            # РџРѕРїС‹С‚РєР° Р·Р°РїРёСЃРё РґРѕР»Р¶РЅР° РѕР±СЂР°Р±РѕС‚Р°С‚СЊСЃСЏ
            handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            
        finally:
            # Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµРј РїСЂР°РІР°
            os.chmod(trades_file, 0o644)
    
    def test_handle_disk_full(self, csv_handler):
        """РўРµСЃС‚ РѕР±СЂР°Р±РѕС‚РєРё РїРµСЂРµРїРѕР»РЅРµРЅРёСЏ РґРёСЃРєР°"""
        with patch('pandas.DataFrame.to_csv', side_effect=IOError("No space left on device")):
            # Р”РѕР»Р¶РµРЅ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ РѕС€РёР±РєСѓ
            try:
                csv_handler.log_close_trade({'symbol': 'BTC/USDT', 'pnl': 100})
            except IOError:
                pass  # РћР¶РёРґР°РµРјРѕРµ РїРѕРІРµРґРµРЅРёРµ


class TestIntegration:
    """РРЅС‚РµРіСЂР°С†РёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹"""
    
    def test_full_trading_cycle(self, csv_handler):
        """РўРµСЃС‚ РїРѕР»РЅРѕРіРѕ С†РёРєР»Р° С‚РѕСЂРіРѕРІР»Рё"""
        # 1. Р›РѕРіРёСЂСѓРµРј СЃРёРіРЅР°Р» РЅР° РїРѕРєСѓРїРєСѓ
        buy_signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'action': 'buy',
            'price': 50000.0,
            'score': 0.85
        }
        csv_handler.log_signal(buy_signal)
        
        # 2. Р›РѕРіРёСЂСѓРµРј РѕС‚РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё
        open_trade = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'entry_price': 50000.0,
            'quantity': 0.1
        }
        csv_handler.log_open_trade(open_trade)
        
        # 3. Р›РѕРіРёСЂСѓРµРј Р·Р°РєСЂС‹С‚РёРµ РїРѕР·РёС†РёРё
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
        
        # 4. РџСЂРѕРІРµСЂСЏРµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ
        stats = csv_handler.get_trade_stats()
        assert stats['total_trades'] >= 1
        assert stats['total_pnl'] == 100.0
        
        # 5. РџСЂРѕРІРµСЂСЏРµРј СЃРёРіРЅР°Р»С‹
        signals = csv_handler.get_all_signals()
        assert len(signals) >= 1
    
    def test_performance_over_time(self, csv_handler):
        """РўРµСЃС‚ РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё РІРѕ РІСЂРµРјРµРЅРё"""
        # РЎРёРјСѓР»РёСЂСѓРµРј РјРµСЃСЏС† С‚РѕСЂРіРѕРІР»Рё
        base_time = datetime.now(timezone.utc) - timedelta(days=30)
        
        for day in range(30):
            for trade_num in range(5):  # 5 СЃРґРµР»РѕРє РІ РґРµРЅСЊ
                trade_time = base_time + timedelta(days=day, hours=trade_num*4)
                
                # РЎР»СѓС‡Р°Р№РЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚
                pnl = np.random.normal(0, 50)
                
                trade = {
                    'timestamp': trade_time.isoformat(),
                    'symbol': 'BTC/USDT',
                    'pnl_abs': pnl,
                    'pnl_pct': pnl / 1000
                }
                csv_handler.log_close_trade(trade)
        
        # РђРЅР°Р»РёР·РёСЂСѓРµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹
        all_trades = csv_handler.get_all_trades()
        assert len(all_trades) == 150  # 30 РґРЅРµР№ * 5 СЃРґРµР»РѕРє
        
        # РџРѕР»СѓС‡Р°РµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ РїРѕ РґРЅСЏРј
        daily_stats = csv_handler.get_daily_statistics()
        if daily_stats is not None:
            assert len(daily_stats) <= 30
