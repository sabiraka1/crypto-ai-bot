from pathlib import Path
import sys

import pytest


# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

@pytest.fixture
def mock_settings(monkeypatch):
    '''Minimal settings for tests'''
    monkeypatch.setenv('MODE', 'paper')
    monkeypatch.setenv('SYMBOLS', 'BTC/USDT')
    monkeypatch.setenv('MTF_W_M15', '0.40')
    monkeypatch.setenv('MTF_W_H1', '0.25')
    monkeypatch.setenv('MTF_W_H4', '0.20')
    monkeypatch.setenv('MTF_W_D1', '0.10')
    monkeypatch.setenv('MTF_W_W1', '0.05')
    monkeypatch.setenv('FUSION_W_TECHNICAL', '0.65')
    monkeypatch.setenv('FUSION_W_AI', '0.35')
    monkeypatch.setenv('EXCHANGE', 'gateio')
    monkeypatch.setenv('BROKER_RATE_RPS', '8')
    monkeypatch.setenv('BROKER_RATE_BURST', '16')
    monkeypatch.setenv('RISK_LOSS_STREAK_LIMIT', '3')
    monkeypatch.setenv('RISK_MAX_DRAWDOWN_PCT', '5.0')
    monkeypatch.setenv('RISK_MAX_SPREAD_PCT', '0.5')
