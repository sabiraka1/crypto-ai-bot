import os
import json
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from trading.risk_manager import AdaptiveRiskManager
from trading.profit_manager import MultiTakeProfitManager
from trading.performance_tracker import RealTimePerformanceTracker
from utils.csv_handler import CSVHandler
from utils.telegram_notifier import send_telegram_message
from exchange_client import ExchangeClient
from config import settings


class PositionManager:
    """
    Продвинутая версия менеджера позиций с:
    - Динамическим риск-менеджментом
    - 4 уровнями тейк-профита + трейлинг-стоп
    - Автоматическим логированием в CSV
    - Интеграцией с Telegram
    - Потокобезопасностью
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.position_file = "open_position.json"
        self.exchange = ExchangeClient()
        self.risk_manager = AdaptiveRiskManager()
        self.profit_manager = MultiTakeProfitManager()
        self.performance_tracker = RealTimePerformanceTracker()
        self.csv_handler = CSVHandler()

        self.current_position: Optional[Dict[str, Any]] = self._load_position()
        self.opening = False

    def _load_position(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self.position_file):
            try:
                with open(self.position_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Ошибка загрузки позиции: {e}")
        return None

    def _save_position(self, position: Dict[str, Any]) -> None:
        try:
            with open(self.position_file, "w") as f:
                json.dump(position, f, indent=4)
        except Exception as e:
            logging.error(f"Ошибка сохранения позиции: {e}")

    def _clear_position(self) -> None:
        if os.path.exists(self.position_file):
            try:
                os.remove(self.position_file)
            except Exception as e:
                logging.error(f"Ошибка удаления файла позиции: {e}")
        self.current_position = None

    def open_position(self, signal: str, price: float, ai_score: float) -> bool:
        """
        Открывает новую позицию с учётом риск-менеджмента и TP уровней
        """
        with self.lock:
            if self.current_position or self.opening:
                logging.warning("Позиция уже открыта или идёт открытие.")
                return False

            self.opening = True

            try:
                # Расчет размера позиции
                position_size, stop_loss = self.risk_manager.calculate_position_size_and_sl(
                    symbol=settings.SYMBOL,
                    entry_price=price,
                    ai_score=ai_score
                )

                # Выставляем ордер
                order = self.exchange.open_market_order(settings.SYMBOL, signal, position_size)
                if not order:
                    raise RuntimeError("Не удалось открыть ордер на бирже.")

                # Устанавливаем TP уровни
                take_profits = self.profit_manager.calculate_tp_levels(price)

                # Логируем открытие
                self.current_position = {
                    "symbol": settings.SYMBOL,
                    "side": signal,
                    "entry_price": price,
                    "position_size": position_size,
                    "stop_loss": stop_loss,
                    "take_profits": take_profits,
                    "open_time": datetime.utcnow().isoformat(),
                    "ai_score": ai_score
                }
                self._save_position(self.current_position)

                # Telegram уведомление
                send_telegram_message(
                    f"📈 Открыта позиция\n"
                    f"Направление: {signal}\n"
                    f"Цена входа: {price}\n"
                    f"Размер: {position_size}\n"
                    f"SL: {stop_loss}\n"
                    f"TP уровни: {take_profits}\n"
                    f"AI Score: {ai_score}"
                )

                return True

            except Exception as e:
                logging.error(f"Ошибка открытия позиции: {e}")
                return False

            finally:
                self.opening = False

    def close_position(self, reason: str, price: Optional[float] = None) -> bool:
        """
        Закрывает текущую позицию с логированием и обновлением статистики
        """
        with self.lock:
            if not self.current_position:
                logging.warning("Нет открытой позиции для закрытия.")
                return False

            try:
                side = "sell" if self.current_position["side"].lower() == "buy" else "buy"
                position_size = self.current_position["position_size"]

                # Закрытие позиции
                order = self.exchange.close_market_order(settings.SYMBOL, side, position_size)
                if not order:
                    raise RuntimeError("Не удалось закрыть ордер на бирже.")

                # Запись в performance tracker
                self.performance_tracker.log_trade_result(
                    symbol=settings.SYMBOL,
                    entry_price=self.current_position["entry_price"],
                    exit_price=price or order.get("price", 0),
                    side=self.current_position["side"],
                    reason=reason,
                    ai_score=self.current_position.get("ai_score", None)
                )

                # Очистка позиции
                self._clear_position()

                # Telegram уведомление
                send_telegram_message(
                    f"📉 Позиция закрыта\n"
                    f"Причина: {reason}\n"
                    f"Цена выхода: {price or order.get('price')}"
                )

                return True

            except Exception as e:
                logging.error(f"Ошибка закрытия позиции: {e}")
                return False

    def check_stop_loss_take_profit(self, current_price: float) -> None:
        """
        Проверяет, достигли ли текущие цены SL или TP
        """
        if not self.current_position:
            return

        stop_loss = self.current_position["stop_loss"]
        take_profits = self.current_position["take_profits"]
        side = self.current_position["side"]

        if side == "buy" and current_price <= stop_loss:
            self.close_position("Stop Loss сработал", current_price)
        elif side == "sell" and current_price >= stop_loss:
            self.close_position("Stop Loss сработал", current_price)

        for tp in take_profits:
            if side == "buy" and current_price >= tp["price"]:
                self.close_position(f"Take Profit {tp['level']}", current_price)
                break
            elif side == "sell" and current_price <= tp["price"]:
                self.close_position(f"Take Profit {tp['level']}", current_price)
                break
