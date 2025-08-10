# utils/trading_metrics.py
"""
Trading Metrics Utility Module
---------------------------------
Универсальные функции расчёта торговых метрик для risk_manager, performance_tracker и других модулей.

Рассчитывает:
- Основные: win rate, profit factor, expectancy
- Риск: Sharpe, Sortino, Calmar, Max Drawdown
- Продвинутые: Kelly, R:R, Volatility, Recovery Factor
- Временные: среднее удержание сделки, сделки в день
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional


# ==========================
# БАЗОВЫЕ МЕТРИКИ
# ==========================

def win_rate(pnl_list: List[float]) -> float:
    """Win Rate — доля прибыльных сделок"""
    if not pnl_list:
        return 0.0
    pnl_arr = np.array(pnl_list)
    return np.sum(pnl_arr > 0) / len(pnl_arr)


def avg_win_loss(pnl_list: List[float]) -> (float, float):
    """Средний % профита и убытка"""
    if not pnl_list:
        return 0.0, 0.0
    pnl_arr = np.array(pnl_list)
    avg_win = pnl_arr[pnl_arr > 0].mean() if np.any(pnl_arr > 0) else 0.0
    avg_loss = pnl_arr[pnl_arr < 0].mean() if np.any(pnl_arr < 0) else 0.0
    return avg_win, avg_loss


def profit_factor(pnl_list: List[float]) -> float:
    """Profit Factor = валовая прибыль / валовый убыток"""
    if not pnl_list:
        return 0.0
    pnl_arr = np.array(pnl_list)
    gross_profit = pnl_arr[pnl_arr > 0].sum()
    gross_loss = abs(pnl_arr[pnl_arr < 0].sum())
    return gross_profit / gross_loss if gross_loss > 0 else np.inf


def expectancy(avg_win: float, avg_loss: float, win_rate: float) -> float:
    """Математическое ожидание сделки"""
    return (win_rate * avg_win) + ((1 - win_rate) * avg_loss)


# ==========================
# РИСК-МЕТРИКИ
# ==========================

def sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02, annual_trades: int = 100) -> float:
    """Sharpe Ratio (annualized)"""
    if len(returns) < 2:
        return 0.0
    excess_returns = np.array(returns) - (risk_free_rate / annual_trades)
    if np.std(returns) == 0:
        return 0.0
    return np.sqrt(annual_trades) * np.mean(excess_returns) / np.std(returns)


def sortino_ratio(returns: List[float], target_return: float = 0.0, annual_trades: int = 100) -> float:
    """Sortino Ratio"""
    if len(returns) < 2:
        return 0.0
    excess_returns = np.array(returns) - target_return
    downside_returns = excess_returns[excess_returns < 0]
    if downside_returns.size == 0:
        return float('inf') if np.mean(excess_returns) > 0 else 0.0
    downside_std = np.std(downside_returns)
    if downside_std == 0:
        return 0.0
    return np.sqrt(annual_trades) * np.mean(excess_returns) / downside_std


def max_drawdown(returns: List[float]) -> float:
    """Максимальная просадка"""
    if not returns:
        return 0.0
    cum_returns = np.cumsum(returns)
    peak = np.maximum.accumulate(cum_returns)
    drawdown = (cum_returns - peak) / 100
    return abs(np.min(drawdown))


def calmar_ratio(returns: List[float], max_dd: float) -> float:
    """Calmar Ratio"""
    if max_dd == 0:
        return 0.0
    annual_return = np.mean(returns) * 100
    return annual_return / (max_dd * 100)


def volatility(returns: List[float]) -> float:
    """Стандартное отклонение (волатильность)"""
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns))


# ==========================
# ПРОДВИНУТЫЕ МЕТРИКИ
# ==========================

def risk_reward_ratio(avg_win: float, avg_loss: float) -> float:
    """Соотношение R:R"""
    if avg_loss == 0:
        return np.inf
    return abs(avg_win / avg_loss)


def recovery_factor(total_net_profit: float, max_dd: float) -> float:
    """Recovery Factor = Общая прибыль / Макс. просадка"""
    if max_dd == 0:
        return np.inf
    return total_net_profit / abs(max_dd)


def kelly_fraction(avg_win: float, avg_loss: float, win_rate: float) -> float:
    """Фракция Келли"""
    if avg_loss >= 0:
        return 0.0
    b = abs(avg_win / avg_loss)
    p = win_rate
    q = 1 - p
    if b == 0:
        return 0.0
    kelly = (b * p - q) / b
    return max(0.0, min(kelly, 0.25))  # Ограничиваем до 25%


# ==========================
# ВРЕМЕННЫЕ МЕТРИКИ
# ==========================

def avg_hold_time(durations_minutes: List[float]) -> float:
    """Среднее удержание сделки в часах"""
    if not durations_minutes:
        return 0.0
    return np.mean(durations_minutes) / 60


def trades_per_day(timestamps: List[datetime]) -> float:
    """Сделок в день"""
    if len(timestamps) <= 1:
        return 0.0
    time_span_days = (max(timestamps) - min(timestamps)).days
    return len(timestamps) / max(time_span_days, 1)


# ==========================
# АЛЕРТЫ ПРОИЗВОДИТЕЛЬНОСТИ
# ==========================

def check_performance_alerts(metrics: Dict[str, Any], thresholds: Dict[str, float]) -> List[str]:
    """Проверка условий для алертов"""
    alerts = []
    if metrics["win_rate"] < thresholds.get("low_win_rate", 0.35):
        alerts.append("LOW_WIN_RATE")
    if metrics["current_drawdown_pct"] > thresholds.get("high_drawdown", 0.15):
        alerts.append("HIGH_DRAWDOWN")
    if metrics["sharpe_ratio"] < thresholds.get("negative_sharpe", 0.0):
        alerts.append("NEGATIVE_SHARPE")
    if metrics.get("consecutive_losses", 0) >= thresholds.get("consecutive_losses", 5):
        alerts.append("CONSECUTIVE_LOSSES")
    if metrics.get("risk_reward", 1) < thresholds.get("poor_risk_reward", 0.5):
        alerts.append("POOR_RISK_REWARD")
    return alerts


# ==========================
# ГЛАВНАЯ ФУНКЦИЯ АНАЛИЗА
# ==========================

def calculate_all_metrics(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Универсальный расчет всех метрик по DataFrame сделок.
    Ожидаемые колонки:
        pnl_pct, pnl_abs, duration_minutes, timestamp
    """
    if trades_df.empty:
        return {}

    pnl_list = trades_df["pnl_pct"].tolist()
    durations = trades_df["duration_minutes"].tolist()
    timestamps = pd.to_datetime(trades_df["timestamp"]).tolist()

    avg_win, avg_loss = avg_win_loss(pnl_list)
    max_dd = max_drawdown(pnl_list)

    metrics = {
        "total_trades": len(trades_df),
        "win_rate": win_rate(pnl_list),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor(pnl_list),
        "total_pnl_pct": sum(pnl_list),
        "sharpe_ratio": sharpe_ratio(pnl_list),
        "sortino_ratio": sortino_ratio(pnl_list),
        "calmar_ratio": calmar_ratio(pnl_list, max_dd),
        "max_drawdown_pct": max_dd,
        "volatility": volatility(pnl_list),
        "expectancy": expectancy(avg_win, avg_loss, win_rate(pnl_list)),
        "kelly_fraction": kelly_fraction(avg_win, avg_loss, win_rate(pnl_list)),
        "risk_reward": risk_reward_ratio(avg_win, avg_loss),
        "recovery_factor": recovery_factor(sum(pnl_list), max_dd),
        "avg_hold_time_hours": avg_hold_time(durations),
        "trades_per_day": trades_per_day(timestamps),
        "last_updated": datetime.now()
    }

    return metrics
