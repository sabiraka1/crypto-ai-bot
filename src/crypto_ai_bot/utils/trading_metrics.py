# utils/trading_metrics.py
"""
Trading Metrics Utility Module
---------------------------------
РЈРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Рµ С„СѓРЅРєС†РёРё СЂР°СЃС‡С‘С‚Р° С‚РѕСЂРіРѕРІС‹С… РјРµС‚СЂРёРє РґР»СЏ risk_manager, performance_tracker Рё РґСЂСѓРіРёС… РјРѕРґСѓР»РµР№.

Р Р°СЃСЃС‡РёС‚С‹РІР°РµС‚:
- РћСЃРЅРѕРІРЅС‹Рµ: win rate, profit factor, expectancy
- Р РёСЃРє: Sharpe, Sortino, Calmar, Max Drawdown
- РџСЂРѕРґРІРёРЅСѓС‚С‹Рµ: Kelly, R:R, Volatility, Recovery Factor
- Р’СЂРµРјРµРЅРЅС‹Рµ: СЃСЂРµРґРЅРµРµ СѓРґРµСЂР¶Р°РЅРёРµ СЃРґРµР»РєРё, СЃРґРµР»РєРё РІ РґРµРЅСЊ
"""

import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional, Union


def _is_empty_or_invalid(data) -> bool:
    """РЈРЅРёРІРµСЂСЃР°Р»СЊРЅР°СЏ РїСЂРѕРІРµСЂРєР° РЅР° РїСѓСЃС‚РѕС‚Сѓ РґР°РЅРЅС‹С…"""
    if data is None:
        return True
    if hasattr(data, 'empty'):  # pandas Series/DataFrame
        return data.empty
    elif hasattr(data, '__len__'):  # СЃРїРёСЃРѕРє, tuple Рё С‚.Рґ.
        return len(data) == 0
    else:
        return not bool(data)


def _to_numpy_array(data: Union[List[float], pd.Series, np.ndarray]) -> np.ndarray:
    """РџСЂРµРѕР±СЂР°Р·РѕРІР°РЅРёРµ РІС…РѕРґРЅС‹С… РґР°РЅРЅС‹С… РІ numpy array"""
    if isinstance(data, pd.Series):
        return data.values
    elif isinstance(data, np.ndarray):
        return data
    else:
        return np.array(data)


# ==========================
# Р‘РђР—РћР’Р«Р• РњР•РўР РРљР
# ==========================

def win_rate(pnl_list: Union[List[float], pd.Series]) -> float:
    """Win Rate вЂ” РґРѕР»СЏ РїСЂРёР±С‹Р»СЊРЅС‹С… СЃРґРµР»РѕРє"""
    if _is_empty_or_invalid(pnl_list):
        return 0.0
    pnl_arr = _to_numpy_array(pnl_list)
    if len(pnl_arr) == 0:
        return 0.0
    return float(np.sum(pnl_arr > 0) / len(pnl_arr))


def avg_win_loss(pnl_list: Union[List[float], pd.Series]) -> tuple[float, float]:
    """РЎСЂРµРґРЅРёР№ % РїСЂРѕС„РёС‚Р° Рё СѓР±С‹С‚РєР°"""
    if _is_empty_or_invalid(pnl_list):
        return 0.0, 0.0
    pnl_arr = _to_numpy_array(pnl_list)
    if len(pnl_arr) == 0:
        return 0.0, 0.0
    
    winning_trades = pnl_arr[pnl_arr > 0]
    losing_trades = pnl_arr[pnl_arr < 0]
    
    avg_win = float(winning_trades.mean()) if len(winning_trades) > 0 else 0.0
    avg_loss = float(losing_trades.mean()) if len(losing_trades) > 0 else 0.0
    
    return avg_win, avg_loss


def profit_factor(pnl_list: Union[List[float], pd.Series]) -> float:
    """Profit Factor = РІР°Р»РѕРІР°СЏ РїСЂРёР±С‹Р»СЊ / РІР°Р»РѕРІС‹Р№ СѓР±С‹С‚РѕРє"""
    if _is_empty_or_invalid(pnl_list):
        return 0.0
    pnl_arr = _to_numpy_array(pnl_list)
    if len(pnl_arr) == 0:
        return 0.0
    
    gross_profit = float(pnl_arr[pnl_arr > 0].sum())
    gross_loss = float(abs(pnl_arr[pnl_arr < 0].sum()))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def expectancy(avg_win: float, avg_loss: float, win_rate_val: float) -> float:
    """РњР°С‚РµРјР°С‚РёС‡РµСЃРєРѕРµ РѕР¶РёРґР°РЅРёРµ СЃРґРµР»РєРё"""
    return (win_rate_val * avg_win) + ((1 - win_rate_val) * avg_loss)


# ==========================
# Р РРЎРљ-РњР•РўР РРљР
# ==========================

def sharpe_ratio(returns: Union[List[float], pd.Series], risk_free_rate: float = 0.02, annual_trades: int = 100) -> float:
    """Sharpe Ratio (annualized)"""
    if _is_empty_or_invalid(returns):
        return 0.0
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) < 2:
        return 0.0
    
    excess_returns = returns_arr - (risk_free_rate / annual_trades)
    returns_std = np.std(returns_arr)
    
    if returns_std == 0:
        return 0.0
    
    return float(np.sqrt(annual_trades) * np.mean(excess_returns) / returns_std)


def sortino_ratio(returns: Union[List[float], pd.Series], target_return: float = 0.0, annual_trades: int = 100) -> float:
    """Sortino Ratio"""
    if _is_empty_or_invalid(returns):
        return 0.0
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) < 2:
        return 0.0
    
    excess_returns = returns_arr - target_return
    downside_returns = excess_returns[excess_returns < 0]
    
    if len(downside_returns) == 0:
        return float('inf') if np.mean(excess_returns) > 0 else 0.0
    
    downside_std = np.std(downside_returns)
    if downside_std == 0:
        return 0.0
    
    return float(np.sqrt(annual_trades) * np.mean(excess_returns) / downside_std)


def max_drawdown(returns: Union[List[float], pd.Series]) -> float:
    """РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РїСЂРѕСЃР°РґРєР°"""
    # РРЎРџР РђР’Р›Р•РќРћ: РєРѕСЂСЂРµРєС‚РЅР°СЏ РїСЂРѕРІРµСЂРєР° РЅР° РїСѓСЃС‚РѕС‚Сѓ РґР»СЏ pandas Series
    if _is_empty_or_invalid(returns):
        return 0.0
    
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) == 0:
        return 0.0
    
    # Р’С‹С‡РёСЃР»СЏРµРј РєСѓРјСѓР»СЏС‚РёРІРЅСѓСЋ РґРѕС…РѕРґРЅРѕСЃС‚СЊ
    cum_returns = np.cumsum(returns_arr)
    peak = np.maximum.accumulate(cum_returns)
    
    # РР·Р±РµРіР°РµРј РґРµР»РµРЅРёСЏ РЅР° РЅРѕР»СЊ
    drawdown = np.where(peak != 0, (cum_returns - peak) / np.abs(peak), 0)
    
    return float(abs(np.min(drawdown)))


def calmar_ratio(returns: Union[List[float], pd.Series], max_dd: Optional[float] = None) -> float:
    """Calmar Ratio"""
    if _is_empty_or_invalid(returns):
        return 0.0
    
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) == 0:
        return 0.0
    
    if max_dd is None:
        max_dd = max_drawdown(returns_arr)
    
    if max_dd == 0:
        return float('inf') if np.mean(returns_arr) > 0 else 0.0
    
    annual_return = float(np.mean(returns_arr) * 252)  # РџСЂРµРґРїРѕР»Р°РіР°РµРј РґРЅРµРІРЅС‹Рµ РґР°РЅРЅС‹Рµ
    return annual_return / (max_dd * 100)


def volatility(returns: Union[List[float], pd.Series]) -> float:
    """РЎС‚Р°РЅРґР°СЂС‚РЅРѕРµ РѕС‚РєР»РѕРЅРµРЅРёРµ (РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ)"""
    if _is_empty_or_invalid(returns):
        return 0.0
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) < 2:
        return 0.0
    return float(np.std(returns_arr))


# ==========================
# РџР РћР”Р’РРќРЈРўР«Р• РњР•РўР РРљР
# ==========================

def risk_reward_ratio(avg_win: float, avg_loss: float) -> float:
    """РЎРѕРѕС‚РЅРѕС€РµРЅРёРµ R:R (С‚Р°РєР¶Рµ РёР·РІРµСЃС‚РЅРѕ РєР°Рє rr_ratio)"""
    if avg_loss == 0:
        return float('inf') if avg_win > 0 else 0.0
    return float(abs(avg_win / avg_loss))


# Р”РѕР±Р°РІР»СЏРµРј Р°Р»РёР°СЃ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃ С‚РµСЃС‚Р°РјРё
def rr_ratio(avg_win: float, avg_loss: float) -> float:
    """РђР»РёР°СЃ РґР»СЏ risk_reward_ratio"""
    return risk_reward_ratio(avg_win, avg_loss)


def recovery_factor(total_net_profit: float, max_dd: float) -> float:
    """Recovery Factor = РћР±С‰Р°СЏ РїСЂРёР±С‹Р»СЊ / РњР°РєСЃ. РїСЂРѕСЃР°РґРєР°"""
    if max_dd == 0:
        return float('inf') if total_net_profit > 0 else 0.0
    return float(total_net_profit / abs(max_dd))


def kelly_fraction(avg_win: float, avg_loss: float, win_rate_val: float) -> float:
    """Р¤СЂР°РєС†РёСЏ РљРµР»Р»Рё"""
    if avg_loss >= 0:
        return 0.0
    
    b = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    p = win_rate_val
    q = 1 - p
    
    if b == 0:
        return 0.0
    
    kelly = (b * p - q) / b
    return float(max(0.0, min(kelly, 0.25)))  # РћРіСЂР°РЅРёС‡РёРІР°РµРј РґРѕ 25%


# ==========================
# Р’Р Р•РњР•РќРќР«Р• РњР•РўР РРљР
# ==========================

def avg_hold_time(durations_minutes: Union[List[float], pd.Series]) -> float:
    """РЎСЂРµРґРЅРµРµ СѓРґРµСЂР¶Р°РЅРёРµ СЃРґРµР»РєРё РІ С‡Р°СЃР°С…"""
    if _is_empty_or_invalid(durations_minutes):
        return 0.0
    durations_arr = _to_numpy_array(durations_minutes)
    if len(durations_arr) == 0:
        return 0.0
    return float(np.mean(durations_arr) / 60)


def trades_per_day(timestamps: Union[List[datetime], pd.Series]) -> float:
    """РЎРґРµР»РѕРє РІ РґРµРЅСЊ"""
    if _is_empty_or_invalid(timestamps):
        return 0.0
    
    if isinstance(timestamps, pd.Series):
        timestamps = timestamps.tolist()
    
    if len(timestamps) <= 1:
        return 0.0
    
    # РљРѕРЅРІРµСЂС‚РёСЂСѓРµРј РІ datetime РµСЃР»Рё РЅСѓР¶РЅРѕ
    datetime_list = []
    for ts in timestamps:
        if isinstance(ts, str):
            datetime_list.append(pd.to_datetime(ts))
        elif isinstance(ts, pd.Timestamp):
            datetime_list.append(ts.to_pydatetime())
        else:
            datetime_list.append(ts)
    
    time_span_days = (max(datetime_list) - min(datetime_list)).days
    return float(len(datetime_list) / max(time_span_days, 1))


# ==========================
# Р”РћРџРћР›РќРРўР•Р›Р¬РќР«Р• РњР•РўР РРљР Р”Р›РЇ РЎРћР’РњР•РЎРўРРњРћРЎРўР РЎ РўР•РЎРўРђРњР
# ==========================

def ulcer_index(equity: Union[pd.Series, List[float]]) -> float:
    """РРЅРґРµРєСЃ Ulcer - РјРµСЂР° СЂРёСЃРєР° РїСЂРѕСЃР°РґРєРё"""
    if _is_empty_or_invalid(equity):
        return 0.0
    
    equity_arr = _to_numpy_array(equity)
    if len(equity_arr) == 0:
        return 0.0
    
    # РќР°С…РѕРґРёРј РјР°РєСЃРёРјР°Р»СЊРЅРѕРµ Р·РЅР°С‡РµРЅРёРµ РЅР° РєР°Р¶РґРѕР№ С‚РѕС‡РєРµ
    running_max = np.maximum.accumulate(equity_arr)
    
    # Р’С‹С‡РёСЃР»СЏРµРј РїСЂРѕС†РµРЅС‚РЅСѓСЋ РїСЂРѕСЃР°РґРєСѓ
    drawdown_pct = np.where(running_max != 0, 
                           100 * (equity_arr - running_max) / running_max, 
                           0)
    
    # Ulcer Index = sqrt(mean(drawdownВІ))
    return float(np.sqrt(np.mean(drawdown_pct ** 2)))


def var_calculation(returns: Union[pd.Series, List[float]], confidence_level: float = 0.05) -> float:
    """Value at Risk (VaR) - РїРѕС‚РµРЅС†РёР°Р»СЊРЅС‹Рµ РїРѕС‚РµСЂРё СЃ Р·Р°РґР°РЅРЅС‹Рј СѓСЂРѕРІРЅРµРј РґРѕРІРµСЂРёСЏ"""
    if _is_empty_or_invalid(returns):
        return 0.0
    
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) == 0:
        return 0.0
    
    return float(np.percentile(returns_arr, confidence_level * 100))


def cvar_calculation(returns: Union[pd.Series, List[float]], confidence_level: float = 0.05) -> float:
    """Conditional Value at Risk (CVaR) - РѕР¶РёРґР°РµРјС‹Рµ РїРѕС‚РµСЂРё Р·Р° VaR"""
    if _is_empty_or_invalid(returns):
        return 0.0
    
    returns_arr = _to_numpy_array(returns)
    if len(returns_arr) == 0:
        return 0.0
    
    var = var_calculation(returns_arr, confidence_level)
    tail_returns = returns_arr[returns_arr <= var]
    
    return float(np.mean(tail_returns)) if len(tail_returns) > 0 else 0.0


# ==========================
# РђР›Р•Р РўР« РџР РћРР—Р’РћР”РРўР•Р›Р¬РќРћРЎРўР
# ==========================

def check_performance_alerts(metrics: Dict[str, Any], thresholds: Dict[str, float]) -> List[str]:
    """РџСЂРѕРІРµСЂРєР° СѓСЃР»РѕРІРёР№ РґР»СЏ Р°Р»РµСЂС‚РѕРІ"""
    alerts = []
    
    if metrics.get("win_rate", 0) < thresholds.get("low_win_rate", 0.35):
        alerts.append("LOW_WIN_RATE")
    
    if metrics.get("current_drawdown_pct", 0) > thresholds.get("high_drawdown", 0.15):
        alerts.append("HIGH_DRAWDOWN")
    
    if metrics.get("sharpe_ratio", 0) < thresholds.get("negative_sharpe", 0.0):
        alerts.append("NEGATIVE_SHARPE")
    
    if metrics.get("consecutive_losses", 0) >= thresholds.get("consecutive_losses", 5):
        alerts.append("CONSECUTIVE_LOSSES")
    
    if metrics.get("risk_reward", 1) < thresholds.get("poor_risk_reward", 0.5):
        alerts.append("POOR_RISK_REWARD")
    
    return alerts


# ==========================
# Р“Р›РђР’РќРђРЇ Р¤РЈРќРљР¦РРЇ РђРќРђР›РР—Рђ
# ==========================

def calculate_all_metrics(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    РЈРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ СЂР°СЃС‡РµС‚ РІСЃРµС… РјРµС‚СЂРёРє РїРѕ DataFrame СЃРґРµР»РѕРє.
    РћР¶РёРґР°РµРјС‹Рµ РєРѕР»РѕРЅРєРё:
        pnl_pct, pnl_abs, duration_minutes, timestamp
    """
    if trades_df.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
            "total_pnl_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "volatility": 0.0,
            "expectancy": 0.0,
            "kelly_fraction": 0.0,
            "risk_reward": 0.0,
            "recovery_factor": 0.0,
            "avg_hold_time_hours": 0.0,
            "trades_per_day": 0.0,
            "last_updated": datetime.now()
        }

    # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ РЅРµРѕР±С…РѕРґРёРјС‹С… РєРѕР»РѕРЅРѕРє
    required_cols = ["pnl_pct"]
    for col in required_cols:
        if col not in trades_df.columns:
            raise ValueError(f"РћС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РѕР±СЏР·Р°С‚РµР»СЊРЅР°СЏ РєРѕР»РѕРЅРєР°: {col}")

    pnl_list = trades_df["pnl_pct"].tolist()
    
    # РћР±СЂР°Р±РѕС‚РєР° РѕРїС†РёРѕРЅР°Р»СЊРЅС‹С… РєРѕР»РѕРЅРѕРє
    durations = trades_df["duration_minutes"].tolist() if "duration_minutes" in trades_df.columns else []
    
    timestamps = []
    if "timestamp" in trades_df.columns:
        timestamps = pd.to_datetime(trades_df["timestamp"]).tolist()

    # Р Р°СЃС‡РµС‚ Р±Р°Р·РѕРІС‹С… РјРµС‚СЂРёРє
    avg_win, avg_loss = avg_win_loss(pnl_list)
    max_dd = max_drawdown(pnl_list)
    win_rate_val = win_rate(pnl_list)

    metrics = {
        "total_trades": len(trades_df),
        "win_rate": win_rate_val,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor(pnl_list),
        "total_pnl_pct": float(sum(pnl_list)),
        "sharpe_ratio": sharpe_ratio(pnl_list),
        "sortino_ratio": sortino_ratio(pnl_list),
        "calmar_ratio": calmar_ratio(pnl_list, max_dd),
        "max_drawdown_pct": max_dd,
        "volatility": volatility(pnl_list),
        "expectancy": expectancy(avg_win, avg_loss, win_rate_val),
        "kelly_fraction": kelly_fraction(avg_win, avg_loss, win_rate_val),
        "risk_reward": risk_reward_ratio(avg_win, avg_loss),
        "recovery_factor": recovery_factor(sum(pnl_list), max_dd),
        "avg_hold_time_hours": avg_hold_time(durations) if durations else 0.0,
        "trades_per_day": trades_per_day(timestamps) if timestamps else 0.0,
        "last_updated": datetime.now()
    }

    return metrics
