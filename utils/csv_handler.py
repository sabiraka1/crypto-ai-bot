import csv
import os
import logging
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from config.settings import (
    CLOSED_TRADES_CSV,
    SIGNALS_CSV,
    LOGS_DIR
)

class CSVHandler:
    # Ваша расширенная структура для сигналов
    SIGNALS_FIELDS = [
        "timestamp",
        "symbol", 
        "signal",
        "ai_score",
        "price",
        "rsi",
        "macd",
        "pattern",
        "take_profit_hit",
        "stop_loss_hit",
        "tp_level_hit",
        "sl_level_hit",
        "profit_pct",
        "trade_duration_min",
        "sharpe_ratio",
        "sortino_ratio",
        "kelly_fraction",
        "max_drawdown",
        "volatility",
        "win_rate"
    ]

    # Ваша расширенная структура для закрытых сделок
    CLOSED_TRADES_FIELDS = [
        "timestamp_open",
        "timestamp_close", 
        "symbol",
        "side",
        "entry_price",
        "exit_price",
        "amount",
        "pnl_pct",
        "pnl_abs",
        "hold_time_min",
        "tp_hit",
        "sl_hit",
        "tp_level_hit",
        "sl_level_hit",
        "sharpe_ratio",
        "sortino_ratio",
        "kelly_fraction",
        "max_drawdown",
        "volatility",
        "win_rate"
    ]

    @staticmethod
    def ensure_csv_exists(file_path: str, fieldnames: List[str]):
        """Создаёт CSV с заголовками, если его нет."""
        try:
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            if not os.path.exists(file_path):
                with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                logging.info(f"CSV создан: {file_path}")
        except Exception as e:
            logging.error(f"Ошибка создания CSV {file_path}: {e}")

    @staticmethod
    def append_to_csv(file_path: str, fieldnames: List[str], data: Dict[str, Any]):
        """Добавляет строку в CSV, создавая файл при необходимости."""
        try:
            CSVHandler.ensure_csv_exists(file_path, fieldnames)
            
            # Фильтруем данные, оставляем только известные поля + заполняем пустые
            filtered_data = {}
            for field in fieldnames:
                filtered_data[field] = data.get(field, "")
                
            with open(file_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(filtered_data)
            logging.debug(f"Запись добавлена в {file_path}")
        except Exception as e:
            logging.error(f"Ошибка записи в CSV {file_path}: {e}")

    @staticmethod
    def log_signal(signal_data: Dict[str, Any]):
        """Логирует сигнал в CSV."""
        CSVHandler.append_to_csv(SIGNALS_CSV, CSVHandler.SIGNALS_FIELDS, signal_data)

    # ДОБАВЛЕНО: критически необходимый метод
    @staticmethod
    def log_signal_snapshot(signal_data: Dict[str, Any]):
        """Алиас для log_signal (нужен для main.py)."""
        CSVHandler.log_signal(signal_data)

    @staticmethod
    def log_closed_trade(trade_data: Dict[str, Any]):
        """Логирует закрытую сделку в CSV."""
        CSVHandler.append_to_csv(CLOSED_TRADES_CSV, CSVHandler.CLOSED_TRADES_FIELDS, trade_data)

    # ДОБАВЛЕНО: критически необходимый метод  
    @staticmethod
    def log_close_trade(trade_data: Dict[str, Any]):
        """Алиас для log_closed_trade (нужен для position_manager)."""
        # Адаптируем данные под вашу схему
        adapted_data = {
            "timestamp_open": trade_data.get("entry_ts", ""),
            "timestamp_close": trade_data.get("close_ts", datetime.now().isoformat()),
            "symbol": trade_data.get("symbol", ""),
            "side": trade_data.get("side", "LONG"),
            "entry_price": trade_data.get("entry_price", 0.0),
            "exit_price": trade_data.get("exit_price", 0.0),
            "amount": trade_data.get("qty_usd", 0.0),
            "pnl_pct": trade_data.get("pnl_pct", 0.0),
            "pnl_abs": trade_data.get("pnl_abs", 0.0),
            "hold_time_min": trade_data.get("duration_minutes", 0.0),
            "tp_hit": trade_data.get("tp_hit", ""),
            "sl_hit": trade_data.get("sl_hit", ""),
            # Остальные поля заполним пустыми для совместимости
            "tp_level_hit": "",
            "sl_level_hit": "",
            "sharpe_ratio": "",
            "sortino_ratio": "",
            "kelly_fraction": "",
            "max_drawdown": "",
            "volatility": "",
            "win_rate": ""
        }
        CSVHandler.log_closed_trade(adapted_data)

    # ДОБАВЛЕНО: метод для открытия сделок
    @staticmethod
    def log_open_trade(trade_data: Dict[str, Any]):
        """Логирует открытие сделки (запись-заглушка для будущего заполнения)."""
        open_data = {
            "timestamp_open": trade_data.get("timestamp", datetime.now().isoformat()),
            "symbol": trade_data.get("symbol", ""),
            "side": trade_data.get("side", "LONG"),
            "entry_price": trade_data.get("entry_price", 0.0),
            "amount": trade_data.get("qty_usd", 0.0),
            # Остальные поля пустые - заполнятся при закрытии
            "timestamp_close": "",
            "exit_price": "",
            "pnl_pct": "",
            "pnl_abs": "",
            "hold_time_min": ""
        }
        CSVHandler.log_closed_trade(open_data)

    @staticmethod
    def read_csv(file_path: str) -> List[Dict[str, Any]]:
        """Читает CSV и возвращает список словарей."""
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except Exception as e:
            logging.error(f"Ошибка чтения CSV {file_path}: {e}")
            return []

    @staticmethod
    def read_csv_safe(file_path: str) -> List[Dict[str, Any]]:
        """Безопасное чтение CSV с обработкой ошибок."""
        try:
            return CSVHandler.read_csv(file_path)
        except Exception as e:
            logging.error(f"Ошибка при чтении CSV {file_path}: {e}")
            return []

    # УЛУЧШЕНО: лучшая обработка ошибок
    @staticmethod
    def get_last_n_trades(n: int) -> List[Dict[str, Any]]:
        """Возвращает последние N сделок."""
        try:
            trades = CSVHandler.read_csv_safe(CLOSED_TRADES_CSV)
            # Фильтруем только завершенные сделки
            completed = [t for t in trades if t.get("exit_price") and str(t.get("exit_price")).strip()]
            return completed[-n:] if completed else []
        except Exception as e:
            logging.error(f"Ошибка получения последних сделок: {e}")
            return []

    @staticmethod
    def read_last_trades(limit: int = 5) -> List[Dict[str, Any]]:
        """Возвращает последние N сделок из закрытых."""
        return CSVHandler.get_last_n_trades(limit)

    # УЛУЧШЕНО: лучшая обработка ошибок + более детальная статистика
    @staticmethod
    def get_trade_stats() -> Dict[str, Any]:
        """Возвращает статистику по сделкам."""
        try:
            trades = CSVHandler.read_csv_safe(CLOSED_TRADES_CSV)
            if not trades:
                return {"count": 0, "win_rate": 0, "avg_pnl": 0}

            # Фильтруем завершенные сделки и валидируем PnL
            valid_trades = []
            for trade in trades:
                if trade.get("exit_price") and str(trade.get("exit_price")).strip():
                    try:
                        pnl = float(trade.get("pnl_pct", 0))
                        valid_trades.append({"trade": trade, "pnl": pnl})
                    except (ValueError, TypeError):
                        continue

            if not valid_trades:
                return {"count": 0, "win_rate": 0, "avg_pnl": 0}

            pnl_values = [t["pnl"] for t in valid_trades]
            wins = [pnl for pnl in pnl_values if pnl > 0]
            
            avg_pnl = sum(pnl_values) / len(pnl_values)
            win_rate = (len(wins) / len(pnl_values)) * 100

            return {
                "count": len(valid_trades),
                "win_rate": round(win_rate, 2),
                "avg_pnl": round(avg_pnl, 2),
                "total_pnl": round(sum(pnl_values), 2),
                "wins": len(wins),
                "losses": len(pnl_values) - len(wins)
            }
        except Exception as e:
            logging.error(f"Ошибка расчета статистики: {e}")
            return {"count": 0, "win_rate": 0, "avg_pnl": 0}

    # ДОБАВЛЕНО: полезная утилита для отладки
    @staticmethod
    def get_csv_info(file_path: str) -> Dict[str, Any]:
        """Возвращает информацию о CSV файле."""
        try:
            if not os.path.exists(file_path):
                return {"exists": False}
            
            data = CSVHandler.read_csv_safe(file_path)
            return {
                "exists": True,
                "rows": len(data),
                "columns": list(data[0].keys()) if data else [],
                "file_size_kb": round(os.path.getsize(file_path) / 1024, 2)
            }
        except Exception as e:
            return {"exists": True, "error": str(e)}


# Инициализация CSV при запуске
try:
    CSVHandler.ensure_csv_exists(SIGNALS_CSV, CSVHandler.SIGNALS_FIELDS)
    CSVHandler.ensure_csv_exists(CLOSED_TRADES_CSV, CSVHandler.CLOSED_TRADES_FIELDS)
    logging.info("📄 CSV файлы инициализированы")
except Exception as e:
    logging.error(f"Ошибка инициализации CSV: {e}")