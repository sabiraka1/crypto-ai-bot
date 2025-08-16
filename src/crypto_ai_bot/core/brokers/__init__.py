# src/crypto_ai_bot/core/brokers/__init__.py
from __future__ import annotations

from typing import Any

from .base import (
    ExchangeInterface,
    ExchangeError,
    TransientExchangeError,
    PermanentExchangeError,
)
from .symbols import (
    ALLOWED_TF,
    normalize_timeframe,
    normalize_symbol,
    split_symbol,
    join_symbol,
    to_exchange_symbol,
)
from .ccxt_exchange import CcxtExchange
from .paper_exchange import PaperExchange
from .backtest_exchange import BacktestExchange

__all__ = [
    "ExchangeInterface",
    "ExchangeError",
    "TransientExchangeError",
    "PermanentExchangeError",
    "ALLOWED_TF",
    "normalize_timeframe",
    "normalize_symbol",
    "split_symbol",
    "join_symbol",
    "to_exchange_symbol",
    "CcxtExchange",
    "PaperExchange",
    "BacktestExchange",
    "create_broker",
]

def create_broker(cfg) -> ExchangeInterface:
    """
    Фабрика брокера по конфигурации:
      - MODE in {"live","paper","backtest"} (регистр не важен)
      - либо флаги PAPER_MODE/BACKTEST_MODE для совместимости
    """
    mode = str(getattr(cfg, "MODE", "") or "").lower()
    paper_flag = bool(getattr(cfg, "PAPER_MODE", False))
    backtest_flag = bool(getattr(cfg, "BACKTEST_MODE", False))

    if mode in {"paper"} or paper_flag:
        return PaperExchange.from_settings(cfg)
    if mode in {"backtest"} or backtest_flag:
        # ожидается, что данные для бэктеста загружает твоя «сцена».
        # если нужно, можно сделать from_csv по пути из cfg.BACKTEST_CSV
        csv_path = getattr(cfg, "BACKTEST_CSV", None)
        if csv_path:
            return BacktestExchange.from_csv(csv_path,
                                             slippage_bps=int(getattr(cfg, "BACKTEST_SLIPPAGE_BPS", 0)),
                                             fee_pct=str(getattr(cfg, "BACKTEST_FEE_PCT", "0.0005")),
                                             balances=getattr(cfg, "BACKTEST_BALANCES", None))
        return BacktestExchange()
    # по умолчанию — реальная биржа через ccxt
    return CcxtExchange.from_settings(cfg)
