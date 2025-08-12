import math
import pandas as pd
import pytest

from utils.trading_metrics import (
    win_rate, avg_win_loss, profit_factor,
    calculate_all_metrics, check_performance_alerts,
    avg_hold_time, trades_per_day
)


def test_basic_functions_win_rate_avg_profit_factor():
    pnl = [0.10, -0.05, 0.00, 0.05]  # 2 выигрыша из 4
    assert win_rate(pnl) == pytest.approx(0.5)

    avg_win, avg_loss = avg_win_loss([-0.10, 0.05, 0.15, -0.05])
    assert avg_win == pytest.approx(0.10)     # (0.05 + 0.15)/2
    assert avg_loss == pytest.approx(-0.075)  # (-0.10 - 0.05)/2

    assert profit_factor([0.05, -0.02, 0.03, -0.01]) == pytest.approx((0.08) / (0.03), rel=1e-6)


def test_calculate_all_metrics_end_to_end():
    df = pd.DataFrame({
        "pnl_pct": [0.05, -0.02, 0.03, -0.01, 0.0],
        "pnl_abs": [5, -2, 3, -1, 0],
        "duration_minutes": [60, 120, 30, 90, 45],
        "timestamp": pd.date_range("2024-01-01", periods=5, freq="D")
    })

    m = calculate_all_metrics(df)
    # Набор ключевых метрик должен присутствовать
    for k in [
        "total_trades", "win_rate", "avg_win_pct", "avg_loss_pct",
        "profit_factor", "max_drawdown_pct", "avg_hold_time_hours", "trades_per_day"
    ]:
        assert k in m

    assert m["total_trades"] == 5
    assert m["win_rate"] == pytest.approx(2/5)
    assert m["profit_factor"] == pytest.approx(0.08 / 0.03, rel=1e-6)
    # (60+120+30+90+45)/5 = 69 минут -> 1.15 ч
    assert m["avg_hold_time_hours"] == pytest.approx(69/60, rel=1e-6)
    # 5 трейдов за 4 дня интервал -> 1.25 в день
    assert m["trades_per_day"] == pytest.approx(5/4, rel=1e-6)
    # Соответствие контракту calculate_all_metrics. :contentReference[oaicite:6]{index=6}


def test_alerts_triggering_all():
    thresholds = {
        "low_win_rate": 0.5,
        "high_drawdown": 0.1,
        "negative_sharpe": 0.0,
        "consecutive_losses": 3,
        "poor_risk_reward": 0.9,
    }
    metrics = {
        "win_rate": 0.4,
        "current_drawdown_pct": 0.2,
        "sharpe_ratio": -0.1,
        "consecutive_losses": 4,
        "risk_reward": 0.4,
    }
    alerts = set(check_performance_alerts(metrics, thresholds))
    assert {"LOW_WIN_RATE", "HIGH_DRAWDOWN", "NEGATIVE_SHARPE", "CONSECUTIVE_LOSSES", "POOR_RISK_REWARD"} <= alerts
    # Логика check_performance_alerts соответствует коду. :contentReference[oaicite:7]{index=7}


def test_time_helpers():
    assert avg_hold_time([60, 120]) == pytest.approx(1.5)  # 180/2/60
    assert trades_per_day(pd.to_datetime(["2024-01-01", "2024-01-03"])) == pytest.approx(1.0)  # 2 за 2 дня
    # Поведение описано в avg_hold_time / trades_per_day. :contentReference[oaicite:8]{index=8}
