import math
from types import SimpleNamespace
from crypto_ai_bot.core import risk

R = risk.rules  # alias for rules module

class DummyPositionsRepo:
    """Dummy positions repo to simulate open positions."""
    def __init__(self, open_positions):
        self._open_positions = open_positions

    def get_open(self):
        return self._open_positions

class DummyTradesRepo:
    """Dummy trades repo for drawdown and loss streak checks."""
    def __init__(self, pnl_since=None, last_closed=None, raise_on_pnl=False, raise_on_closed=False):
        self.pnl_since = pnl_since if pnl_since is not None else (0.0, 0.0)
        self.last_closed = last_closed if last_closed is not None else []
        self.raise_on_pnl = raise_on_pnl
        self.raise_on_closed = raise_on_closed

    def realized_pnl_since_ms(self, since_ms):
        if self.raise_on_pnl:
            raise Exception("DB error")
        return self.pnl_since

    def get_last_closed(self, n=1):
        if self.raise_on_closed:
            raise Exception("DB error")
        return self.last_closed[:n]

def test_check_max_exposure_no_positions():
    """Тест: при отсутствии открытых позиций ограничение по экспозиции не блокирует торговлю."""
    settings = SimpleNamespace(RISK_MAX_POSITIONS=3)
    positions_repo = DummyPositionsRepo(open_positions=[])
    result = R.check_max_exposure(settings, positions_repo=positions_repo, symbol="BTC-USDT")
    assert result["ok"] is True
    assert result.get("code") == "ok"

def test_check_max_exposure_concurrent_position():
    """Тест: если по тому же инструменту уже есть открытая позиция, торговля блокируется."""
    settings = SimpleNamespace(RISK_MAX_POSITIONS=3)
    positions_repo = DummyPositionsRepo(open_positions=[{"symbol": "BTC-USDT", "qty": 1.0}])
    result = R.check_max_exposure(settings, positions_repo=positions_repo, symbol="BTC-USDT")
    assert result["ok"] is False
    assert result.get("code") == "concurrent_position_blocked"

def test_check_max_exposure_limit_exceeded():
    """Тест: при превышении максимального числа одновременных позиций торговля блокируется."""
    settings = SimpleNamespace(RISK_MAX_POSITIONS=1)  # лимит 1 позиция
    positions_repo = DummyPositionsRepo(open_positions=[{"symbol": "ETH-USDT", "qty": 2.0}])
    # Попытка открыть новую позицию по другому символу -> превышение лимита
    result = R.check_max_exposure(settings, positions_repo=positions_repo, symbol="BTC-USDT")
    assert result["ok"] is False
    assert result.get("code") == "max_positions_exceeded"
    # Без указания символа (любая новая позиция)
    result2 = R.check_max_exposure(settings, positions_repo=positions_repo, symbol=None)
    assert result2["ok"] is False
    assert result2.get("code") == "max_positions_exceeded"

def test_check_drawdown_within_limit():
    """Тест: если просадка не превышает лимит, торговля не блокируется."""
    settings = SimpleNamespace(RISK_MAX_DRAWDOWN_PCT=10.0, RISK_DRAWDOWN_LOOKBACK_DAYS=7)
    trades_repo = DummyTradesRepo(pnl_since=(-50.0, 1000.0))  # -5% просадка
    result = R.check_drawdown(settings, trades_repo=trades_repo, lookback_days=7)
    assert result["ok"] is True
    assert result.get("code") == "ok"
    # Сценарий без сделок (basis=0) -> просадка 0%, не блокируем
    trades_repo2 = DummyTradesRepo(pnl_since=(0.0, 0.0))
    result2 = R.check_drawdown(settings, trades_repo=trades_repo2, lookback_days=7)
    assert result2["ok"] is True

def test_check_drawdown_limit_exceeded():
    """Тест: при превышении допустимого уровня просадки торговля блокируется."""
    settings = SimpleNamespace(RISK_MAX_DRAWDOWN_PCT=10.0, RISK_DRAWDOWN_LOOKBACK_DAYS=7)
    trades_repo = DummyTradesRepo(pnl_since=(-150.0, 1000.0))  # -15% просадка
    result = R.check_drawdown(settings, trades_repo=trades_repo, lookback_days=7)
    assert result["ok"] is False
    assert result.get("code") == "drawdown_limit"
    details = result.get("details", {})
    assert "pnl_pct" in details and math.isclose(details["pnl_pct"], -15.0, rel_tol=1e-2)
    assert "limit_pct" in details and details["limit_pct"] == pytest.approx(10.0)

def test_check_drawdown_with_error():
    """Тест: в случае ошибки при расчете PnL просадка не блокируется (безопасный режим)."""
    settings = SimpleNamespace(RISK_MAX_DRAWDOWN_PCT=5.0)
    trades_repo = DummyTradesRepo(raise_on_pnl=True)  # эмуляция ошибки базы данных
    result = R.check_drawdown(settings, trades_repo=trades_repo, lookback_days=1)
    # Ошибка трактуется как отсутствие просадки -> ok
    assert result["ok"] is True

def test_check_sequence_losses_not_triggered():
    """Тест: если недостаточно подряд убыточных сделок, блокировка не срабатывает."""
    settings = SimpleNamespace(RISK_MAX_LOSSES=3)
    # Менее 3 последних сделок (или не все убыточны)
    last_trades = [{"pnl": -10.0}, {"pnl": -5.0}]
    trades_repo = DummyTradesRepo(last_closed=last_trades)
    result = R.check_sequence_losses(settings, trades_repo=trades_repo, max_losses=3)
    assert result["ok"] is True
    # В списке 3 сделки, но одна прибыльная
    last_trades2 = [{"pnl": -20.0}, {"pnl": -15.0}, {"pnl": 5.0}]
    trades_repo2 = DummyTradesRepo(last_closed=last_trades2)
    result2 = R.check_sequence_losses(settings, trades_repo=trades_repo2, max_losses=3)
    assert result2["ok"] is True

def test_check_sequence_losses_triggered():
    """Тест: если подряд произошло N убыточных сделок, торговля блокируется."""
    settings = SimpleNamespace(RISK_MAX_LOSSES=3)
    # 3 подряд убыточных сделки
    last_trades = [{"pnl": -1.0}, {"pnl": -2.0}, {"pnl": -3.0}]
    trades_repo = DummyTradesRepo(last_closed=last_trades)
    result = R.check_sequence_losses(settings, trades_repo=trades_repo, max_losses=3)
    assert result["ok"] is False
    assert result.get("code") == "loss_streak"
    details = result.get("details", {})
    assert details.get("losses") == 3

def test_check_sequence_losses_with_error():
    """Тест: в случае ошибки при получении истории сделок торговля блокируется (fail-safe)."""
    settings = SimpleNamespace(RISK_MAX_LOSSES=3)
    trades_repo = DummyTradesRepo(raise_on_closed=True)
    result = R.check_sequence_losses(settings, trades_repo=trades_repo, max_losses=3)
    assert result["ok"] is False
    assert result.get("code") == "loss_streak_check_failed"
