from __future__ import annotations

from typing import Dict, Any

from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec


class PositionsReconciler:
    """
    Reconciler для сверки позиций между локальным хранилищем и биржей.
    Сравнивает base_qty из БД с free_base с биржи.
    """
    
    def __init__(self, *, storage: Storage, broker: IBroker, symbol: str) -> None:
        self._storage = storage
        self._broker = broker
        self._symbol = symbol
        self._log = get_logger("recon.positions")

    async def run_once(self) -> Dict[str, Any]:
        """
        Выполнить одну сверку позиции.
        
        Returns:
            Dict с результатами сверки:
            - symbol: торговый символ
            - local_base: количество base актива в локальной БД
            - exchange_base: количество free base актива на бирже
            - diff: разница (exchange - local)
            - ok: флаг успешности сверки
        """
        # Парсим символ для получения base/quote
        sym = parse_symbol(self._symbol)
        
        # Получаем локальную позицию из БД
        local_base = self._storage.positions.get_base_qty(self._symbol) or dec("0")
        
        # Получаем баланс с биржи
        bal = await self._broker.fetch_balance(self._symbol)
        base_bal = bal.free_base
        
        # Вычисляем расхождение
        diff = base_bal - local_base
        
        # Логируем результаты
        self._log.info("position_checked", extra={
            "symbol": self._symbol, 
            "local_base": str(local_base), 
            "exchange_base": str(base_bal), 
            "diff": str(diff)
        })
        
        # Если есть существенное расхождение, можно добавить предупреждение
        if abs(diff) > dec("0.00000001"):  # минимальный порог для предупреждения
            self._log.warning("position_discrepancy", extra={
                "symbol": self._symbol,
                "diff": str(diff),
                "local": str(local_base),
                "exchange": str(base_bal)
            })
        
        return {
            "symbol": self._symbol, 
            "local_base": str(local_base), 
            "exchange_base": str(base_bal), 
            "diff": str(diff), 
            "ok": True
        }