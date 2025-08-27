from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Any


@dataclass
class LossStreakRule:
    """Правило ограничения серии убыточных сделок."""
    
    max_streak: int = 3
    lookback_trades: int = 10
    
    def check(self, recent_trades: List[Dict[str, Any]]) -> tuple[bool, str]:
        """
        Проверяет текущую серию убытков.
        Returns: (allowed, reason)
        """
        if not recent_trades:
            return True, "no_trades"
        
        # Считаем текущую серию убытков
        current_streak = 0
        for trade in reversed(recent_trades[-self.lookback_trades:]):
            pnl = Decimal(str(trade.get("cost", 0)))
            side = str(trade.get("side", "")).lower()
            
            # Для buy отрицательный cost = покупка (убыток пока не продали)
            # Для sell положительный cost = продажа (может быть прибыль или убыток)
            if side == "buy":
                # Пока не закрыта позиция - не считаем
                continue
            elif side == "sell" and pnl <= 0:
                current_streak += 1
            else:
                break  # Прибыльная сделка прерывает серию
        
        if current_streak >= self.max_streak:
            return False, f"loss_streak_{current_streak}_of_{self.max_streak}"
        
        return True, f"streak_{current_streak}"
    
    def calculate_streak(self, trades: List[Dict[str, Any]]) -> int:
        """Подсчёт максимальной серии убытков в истории."""
        max_streak = 0
        current_streak = 0
        
        for trade in trades:
            side = str(trade.get("side", "")).lower()
            if side != "sell":
                continue
                
            pnl = Decimal(str(trade.get("cost", 0)))
            if pnl <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak