import logging
import os
import csv
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import deque
from enum import Enum

# === РРјРїРѕСЂС‚ RiskManager ===
try:
    from trading.risk_manager import RiskManager
except ImportError:
    RiskManager = None

# === РРјРїРѕСЂС‚ Trading Metrics ===
from utils.trading_metrics import calculate_all_metrics, check_performance_alerts

LOGS_DIR = "logs"
PERFORMANCE_CSV = os.path.join(LOGS_DIR, "performance_history.csv")
os.makedirs(LOGS_DIR, exist_ok=True)


class PerformanceAlert(Enum):
    LOW_WIN_RATE = "low_win_rate"
    HIGH_DRAWDOWN = "high_drawdown"
    NEGATIVE_SHARPE = "negative_sharpe"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    POOR_RISK_REWARD = "poor_risk_reward"


@dataclass
class TradeResult:
    timestamp: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl_abs: float
    pnl_pct: float
    duration_minutes: float
    reason: str
    buy_score: Optional[float] = None
    ai_score: Optional[float] = None
    market_condition: Optional[str] = None


@dataclass
class PerformanceMetrics:
    total_trades: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    total_pnl_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    current_drawdown_pct: float
    volatility: float
    sortino_ratio: float
    calmar_ratio: float
    expectancy: float
    kelly_fraction: float
    avg_hold_time_hours: float
    trades_per_day: float
    last_updated: datetime


class RealTimePerformanceTracker:
    def __init__(self, max_trades_history: int = 500, auto_save_csv: bool = True):
        self.max_trades_history = max_trades_history
        self.trades_history = deque(maxlen=max_trades_history)
        self.daily_pnl = deque(maxlen=365)
        self.auto_save_csv = auto_save_csv

        self.alert_thresholds = {
            "low_win_rate": 0.35,
            "high_drawdown": 0.15,
            "negative_sharpe": 0.0,
            "consecutive_losses": 5,
            "poor_risk_reward": 0.5
        }

        self._metrics_cache: Optional[PerformanceMetrics] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=5)

        self.consecutive_losses = 0
        self.peak_balance = 0.0
        self.current_balance = 0.0

        self.risk_manager = RiskManager() if RiskManager else None

        logging.info("рџ“Љ Performance tracker initialized with extended metrics")

    # === Р”РѕР±Р°РІР»РµРЅРёРµ СЂРµР·СѓР»СЊС‚Р°С‚Р° СЃРґРµР»РєРё ===
    def add_trade_result(self, trade: TradeResult) -> None:
        self.trades_history.append(trade)

        if trade.pnl_pct > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

        self.current_balance += trade.pnl_abs
        self.peak_balance = max(self.peak_balance, self.current_balance)

        self._metrics_cache = None

        if self.auto_save_csv:
            self._save_trade_to_csv(trade)

        # РџСЂРѕРІРµСЂРєР° Р°Р»РµСЂС‚РѕРІ
        alerts = self.check_performance_alerts()
        if alerts:
            self._log_alerts(alerts)
            if self.risk_manager:
                should_pause, reason = self.should_pause_trading()
                if should_pause:
                    self.risk_manager.pause_trading(reason)

    # === Р Р°СЃС‡РµС‚ С‚РµРєСѓС‰РёС… РјРµС‚СЂРёРє ===
    def get_current_metrics(self, force_recalculate: bool = False) -> PerformanceMetrics:
        if (
            not force_recalculate
            and self._metrics_cache
            and self._cache_timestamp
            and datetime.now() - self._cache_timestamp < self._cache_duration
        ):
            return self._metrics_cache

        if len(self.trades_history) == 0:
            return self._empty_metrics()

        trades_df = pd.DataFrame([asdict(trade) for trade in self.trades_history])

        # Р’С‹Р·С‹РІР°РµРј С†РµРЅС‚СЂР°Р»РёР·РѕРІР°РЅРЅС‹Р№ СЂР°СЃС‡РµС‚ РјРµС‚СЂРёРє
        all_metrics = calculate_all_metrics(trades_df)

        metrics = PerformanceMetrics(
            total_trades=all_metrics.get("total_trades", 0),
            win_rate=all_metrics.get("win_rate", 0.0),
            avg_win_pct=all_metrics.get("avg_win_pct", 0.0),
            avg_loss_pct=all_metrics.get("avg_loss_pct", 0.0),
            profit_factor=all_metrics.get("profit_factor", 0.0),
            total_pnl_pct=all_metrics.get("total_pnl_pct", 0.0),
            sharpe_ratio=all_metrics.get("sharpe_ratio", 0.0),
            max_drawdown_pct=all_metrics.get("max_drawdown_pct", 0.0),
            current_drawdown_pct=self._calculate_current_drawdown(),
            volatility=all_metrics.get("volatility", 0.0),
            sortino_ratio=all_metrics.get("sortino_ratio", 0.0),
            calmar_ratio=all_metrics.get("calmar_ratio", 0.0),
            expectancy=all_metrics.get("expectancy", 0.0),
            kelly_fraction=all_metrics.get("kelly_fraction", 0.0),
            avg_hold_time_hours=all_metrics.get("avg_hold_time_hours", 0.0),
            trades_per_day=all_metrics.get("trades_per_day", 0.0),
            last_updated=datetime.now()
        )

        self._metrics_cache = metrics
        self._cache_timestamp = datetime.now()
        return metrics

    # === РўРµР»РµРіСЂР°Рј РѕС‚С‡С‘С‚ ===
    def get_telegram_report(self) -> str:
        metrics = self.get_current_metrics()
        return (
            f"рџ“Љ *Performance Summary*\n"
            f"Trades: {metrics.total_trades}\n"
            f"Win Rate: {metrics.win_rate:.1%}\n"
            f"Total PnL: {metrics.total_pnl_pct:.2f}%\n"
            f"Sharpe: {metrics.sharpe_ratio:.2f} | Sortino: {metrics.sortino_ratio:.2f}\n"
            f"Max DD: {metrics.max_drawdown_pct:.2%} | Curr DD: {metrics.current_drawdown_pct:.2%}\n"
            f"Profit Factor: {metrics.profit_factor:.2f}\n"
            f"Kelly Fraction: {metrics.kelly_fraction:.2f}\n"
            f"Last Updated: {metrics.last_updated.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    # === РџСЂРѕРІРµСЂРєР° Р°РІС‚Рѕ-РїР°СѓР·С‹ ===
    def should_pause_trading(self) -> Tuple[bool, str]:
        alerts = self.check_performance_alerts()
        critical_alerts = [PerformanceAlert.HIGH_DRAWDOWN.value, PerformanceAlert.CONSECUTIVE_LOSSES.value]
        if any(alert in alerts for alert in critical_alerts):
            if PerformanceAlert.HIGH_DRAWDOWN.value in alerts:
                return True, f"High drawdown: {self.get_current_metrics().current_drawdown_pct:.2%}"
            if PerformanceAlert.CONSECUTIVE_LOSSES.value in alerts:
                return True, f"Consecutive losses: {self.consecutive_losses}"
        if len(alerts) >= 3:
            return True, f"Multiple performance issues: {alerts}"
        return False, ""

    # === РЎРѕС…СЂР°РЅРµРЅРёРµ СЃРґРµР»РєРё РІ CSV ===
    def _save_trade_to_csv(self, trade: TradeResult):
        file_exists = os.path.isfile(PERFORMANCE_CSV)
        with open(PERFORMANCE_CSV, mode="a", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=asdict(trade).keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(asdict(trade))

    # === РўРµРєСѓС‰Р°СЏ РїСЂРѕСЃР°РґРєР° ===
    def _calculate_current_drawdown(self) -> float:
        if self.peak_balance == 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / abs(self.peak_balance)

    # === РџСѓСЃС‚С‹Рµ РјРµС‚СЂРёРєРё ===
    def _empty_metrics(self) -> PerformanceMetrics:
        return PerformanceMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, datetime.now())

    # === Р›РѕРіРёСЂРѕРІР°РЅРёРµ Р°Р»РµСЂС‚РѕРІ ===
    def _log_alerts(self, alerts: List[str]):
        for alert in alerts:
            logging.warning(f"вљ пёЏ Performance Alert: {alert}")

    # === РџСЂРѕРІРµСЂРєР° Р°Р»РµСЂС‚РѕРІ ===
    def check_performance_alerts(self) -> List[str]:
        metrics_dict = calculate_all_metrics(pd.DataFrame([asdict(trade) for trade in self.trades_history]))
        metrics_dict["current_drawdown_pct"] = self._calculate_current_drawdown()
        metrics_dict["consecutive_losses"] = self.consecutive_losses
        return check_performance_alerts(metrics_dict, self.alert_thresholds)









