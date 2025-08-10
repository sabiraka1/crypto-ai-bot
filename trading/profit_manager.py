import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import os

# Локальные импорты
from utils.telegram_utils import send_telegram_message
from trading.trade_engine import close_partial_position

CLOSED_TRADES_FILE = "closed_trades.csv"

class TPStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"

@dataclass
class TakeProfitLevel:
    level_id: str
    target_price: float
    size_fraction: float
    tp_type: str
    status: TPStatus
    created_at: datetime
    executed_at: Optional[datetime] = None
    actual_price: Optional[float] = None

class MultiTakeProfitManager:
    def __init__(self):
        self.default_tp_levels = [
            {"id": "tp1_quick", "pct": 0.6, "size": 0.25, "type": "fixed"},
            {"id": "tp2_standard", "pct": 1.2, "size": 0.30, "type": "fixed"},
            {"id": "tp3_extended", "pct": 2.0, "size": 0.25, "type": "atr_based"},
            {"id": "tp4_trailing", "pct": 0.0, "size": 0.20, "type": "trailing"}
        ]
        self.volatility_adjustment_factor = 2.0
        self.trend_strength_factor = 1.5
        self.volume_confirmation_threshold = 1.2
        self.min_tp_distance = 0.003
        self.max_tp_distance = 0.05
        self.active_levels: Dict[str, List[TakeProfitLevel]] = {}

    def create_tp_levels(self, position_id: str, entry_price: float, df: pd.DataFrame,
                         market_condition: str, trend_strength: float = 0.0) -> List[TakeProfitLevel]:
        volatility = self._calculate_volatility(df)
        atr = self._calculate_atr(df)
        volume_profile = self._analyze_volume_profile(df)
        tp_levels = []

        for i, cfg in enumerate(self.default_tp_levels):
            if cfg["type"] == "trailing":
                continue
            adapted_pct = self._adapt_tp_percentage(cfg["pct"], volatility, trend_strength,
                                                    market_condition, volume_profile)

            if cfg["type"] == "atr_based":
                atr_multiplier = 2.0 + (i * 0.5)
                target_price = entry_price + (atr * atr_multiplier * (1 + trend_strength))
            else:
                target_price = entry_price * (1 + adapted_pct / 100)

            price_diff_pct = (target_price - entry_price) / entry_price
            if price_diff_pct < self.min_tp_distance:
                target_price = entry_price * (1 + self.min_tp_distance)
            elif price_diff_pct > self.max_tp_distance:
                target_price = entry_price * (1 + self.max_tp_distance)

            tp_levels.append(TakeProfitLevel(
                level_id=f"{position_id}_{cfg['id']}",
                target_price=target_price,
                size_fraction=cfg["size"],
                tp_type=cfg["type"],
                status=TPStatus.PENDING,
                created_at=datetime.now()
            ))

        self.active_levels[position_id] = tp_levels
        logging.info(f"💰 Created {len(tp_levels)} TP levels for position {position_id}")
        return tp_levels

    def check_tp_executions(self, position_id: str, current_price: float, current_volume: float = None) -> List[TakeProfitLevel]:
        if position_id not in self.active_levels:
            return []
        executed = []
        for level in self.active_levels[position_id]:
            if level.status != TPStatus.PENDING:
                continue
            should_execute = current_price >= level.target_price
            if should_execute and level.size_fraction > 0.3 and current_volume is not None:
                if current_volume < self.volume_confirmation_threshold:
                    should_execute = False
            if should_execute:
                level.status = TPStatus.EXECUTED
                level.executed_at = datetime.now()
                level.actual_price = current_price
                executed.append(level)

                close_partial_position(position_id, level.size_fraction, current_price)
                self._log_closed_trade(position_id, level)
                send_telegram_message(
                    f"✅ TP hit: {level.level_id}\n💵 Price: {current_price:.6f}\n📊 Size: {level.size_fraction*100:.0f}%"
                )
        return executed

    def create_trailing_tp(self, position_id: str, entry_price: float, current_price: float, atr: float) -> Optional[TakeProfitLevel]:
        current_profit_pct = (current_price - entry_price) / entry_price * 100
        if current_profit_pct < 1.0:
            return None
        trailing_level = TakeProfitLevel(
            level_id=f"{position_id}_trailing",
            target_price=current_price - (atr * 1.5),
            size_fraction=1.0,
            tp_type="trailing",
            status=TPStatus.PENDING,
            created_at=datetime.now()
        )
        self.active_levels.setdefault(position_id, []).append(trailing_level)
        logging.info(f"📈 Trailing TP activated for {position_id} at {trailing_level.target_price:.6f}")
        return trailing_level

    def update_trailing_tp(self, position_id: str, max_price: float, atr: float) -> Tuple[bool, float]:
        trailing_level = next((l for l in self.active_levels.get(position_id, [])
                               if l.tp_type == "trailing" and l.status == TPStatus.PENDING), None)
        if not trailing_level:
            return False, 0.0
        new_price = max_price - (atr * 1.5)
        if new_price > trailing_level.target_price:
            old_price = trailing_level.target_price
            trailing_level.target_price = new_price
            logging.info(f"📊 Trailing TP updated: {old_price:.6f} → {new_price:.6f}")
            return True, new_price
        return False, trailing_level.target_price

    def get_remaining_position_size(self, position_id: str) -> float:
        executed_size = sum(l.size_fraction for l in self.active_levels.get(position_id, [])
                            if l.status == TPStatus.EXECUTED and l.tp_type != "trailing")
        return max(0.0, 1.0 - executed_size)

    def get_next_tp_target(self, position_id: str) -> Optional[TakeProfitLevel]:
        pending = [l for l in self.active_levels.get(position_id, [])
                   if l.status == TPStatus.PENDING and l.tp_type != "trailing"]
        return min(pending, key=lambda x: x.target_price) if pending else None

    def cancel_all_tp_levels(self, position_id: str, reason: str = "position_closed"):
        for level in self.active_levels.get(position_id, []):
            if level.status == TPStatus.PENDING:
                level.status = TPStatus.CANCELLED
        logging.info(f"❌ All TP levels cancelled for {position_id}: {reason}")

    def get_tp_summary(self, position_id: str) -> Dict[str, Any]:
        levels = self.active_levels.get(position_id, [])
        executed = [l for l in levels if l.status == TPStatus.EXECUTED]
        pending = [l for l in levels if l.status == TPStatus.PENDING]
        total_exec_size = sum(l.size_fraction for l in executed if l.tp_type != "trailing")
        return {
            "total_levels": len(levels),
            "executed_count": len(executed),
            "pending_count": len(pending),
            "executed_size_fraction": total_exec_size,
            "remaining_size_fraction": 1.0 - total_exec_size,
            "next_target": self.get_next_tp_target(position_id),
            "has_trailing": any(l.tp_type == "trailing" for l in levels)
        }

    def _log_closed_trade(self, position_id: str, level: TakeProfitLevel):
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "position_id": position_id,
            "level_id": level.level_id,
            "price": level.actual_price,
            "size_fraction": level.size_fraction,
            "type": level.tp_type
        }
        file_exists = os.path.isfile(CLOSED_TRADES_FILE)
        pd.DataFrame([row]).to_csv(CLOSED_TRADES_FILE, mode='a', index=False, header=not file_exists)

    # ===== Вспомогательные =====
    def _adapt_tp_percentage(self, base_pct: float, volatility: float, trend_strength: float,
                             market_condition: str, volume_profile: Dict) -> float:
        adapted_pct = base_pct * (1 + volatility * self.volatility_adjustment_factor)
        if trend_strength > 0.5:
            adapted_pct *= (1 + trend_strength * self.trend_strength_factor)
        market_adj = {
            "STRONG_BULL": 1.3, "WEAK_BULL": 1.1, "SIDEWAYS": 0.9,
            "WEAK_BEAR": 0.8, "STRONG_BEAR": 0.7
        }.get(market_condition, 1.0)
        adapted_pct *= market_adj
        if volume_profile.get("above_average", False):
            adapted_pct *= 1.1
        return max(adapted_pct, base_pct * 0.5)

    def _calculate_volatility(self, df: pd.DataFrame, period: int = 20) -> float:
        if len(df) < period:
            return 0.03
        return float(df['close'].pct_change().rolling(period).std().iloc[-1] or 0.03)

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return df['close'].iloc[-1] * 0.02
        high, low, close = df['high'], df['low'], df['close']
        prev_close = close.shift(1)
        tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1] or df['close'].iloc[-1] * 0.02)

    def _analyze_volume_profile(self, df: pd.DataFrame, period: int = 20) -> Dict[str, Any]:
        if len(df) < period:
            return {"above_average": False, "volume_trend": "neutral"}
        volume_ma = df['volume'].rolling(period).mean()
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / (volume_ma.iloc[-1] or 1)
        recent_vol, old_vol = volume_ma.iloc[-5:].mean(), volume_ma.iloc[-15:-10].mean()
        trend = "increasing" if recent_vol > old_vol * 1.1 else \
                "decreasing" if recent_vol < old_vol * 0.9 else "neutral"
        return {"above_average": volume_ratio > 1.2, "volume_ratio": volume_ratio, "volume_trend": trend}
