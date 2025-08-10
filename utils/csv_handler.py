import csv
import os
import logging
from datetime import datetime
from config.settings import (
    CLOSED_TRADES_CSV,
    SIGNALS_CSV,
    LOGS_DIR
)

class CSVHandler:
    # Расширенная структура для сигналов
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

    # Расширенная структура для закрытых сделок
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
    def ensure_csv_exists(file_path: str, fieldnames: list):
        """Создаёт CSV с заголовками, если его нет."""
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        if not os.path.exists(file_path):
            with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logging.info(f"CSV создан: {file_path}")

    @staticmethod
    def append_to_csv(file_path: str, fieldnames: list, data: dict):
        """Добавляет строку в CSV, создавая файл при необходимости."""
        CSVHandler.ensure_csv_exists(file_path, fieldnames)
        with open(file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writerow(data)
        logging.debug(f"Запись добавлена в {file_path}: {data}")

    @staticmethod
    def log_signal(signal_data: dict):
        """Логирует сигнал в CSV."""
        CSVHandler.append_to_csv(SIGNALS_CSV, CSVHandler.SIGNALS_FIELDS, signal_data)

    @staticmethod
    def log_closed_trade(trade_data: dict):
        """Логирует закрытую сделку в CSV."""
        CSVHandler.append_to_csv(CLOSED_TRADES_CSV, CSVHandler.CLOSED_TRADES_FIELDS, trade_data)

    @staticmethod
    def read_csv(file_path: str) -> list:
        """Читает CSV и возвращает список словарей."""
        if not os.path.exists(file_path):
            return []
        with open(file_path, mode="r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    @staticmethod
    def get_last_n_trades(n: int) -> list:
        """Возвращает последние N сделок."""
        trades = CSVHandler.read_csv(CLOSED_TRADES_CSV)
        return trades[-n:] if trades else []

    @staticmethod
    def get_trade_stats():
        """Возвращает статистику по сделкам."""
        trades = CSVHandler.read_csv(CLOSED_TRADES_CSV)
        if not trades:
            return {"count": 0, "win_rate": 0, "avg_pnl": 0}

        wins = [t for t in trades if float(t.get("pnl_pct", 0)) > 0]
        avg_pnl = sum(float(t.get("pnl_pct", 0)) for t in trades) / len(trades)
        win_rate = (len(wins) / len(trades)) * 100

        return {
            "count": len(trades),
            "win_rate": round(win_rate, 2),
            "avg_pnl": round(avg_pnl, 2)
        }


# Инициализация CSV при запуске
CSVHandler.ensure_csv_exists(CSVHandler.SIGNALS_CSV, CSVHandler.SIGNALS_FIELDS)
CSVHandler.ensure_csv_exists(CSVHandler.CLOSED_TRADES_CSV, CSVHandler.CLOSED_TRADES_FIELDS)
