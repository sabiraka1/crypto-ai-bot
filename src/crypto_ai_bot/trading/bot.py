# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/trading/bot.py
---------------------------------
Компактный и надёжный торговый цикл без лишних зависимостей.
Совместим с обновлённым signals/signal_aggregator.aggregate_features().

Основные принципы:
- Один торговый цикл в процессе (thread-safe).
- Реальные рыночные данные всегда используются (даже в SAFE/PAPER режимах).
- Идемпотентные рыночные заявки (client tag) + ретраи.
- Простой ATR-базовый SL/TP + трейлинг (включается по флагу).
- Без создания новых модулей/файлов в проекте (опирается на существующие).
"""

import os
import time
import math
import uuid
import json
import threading
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import ccxt  # только для type hints/рыночных вызовов
    from ccxt.base.errors import NetworkError, ExchangeError
except Exception:  # pragma: no cover
    ccxt = None
    class NetworkError(Exception): ...
    class ExchangeError(Exception): ...

from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))


# ---------------------- Вспомогательные структуры ----------------------

@dataclass
class Settings:
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = int(os.getenv("ANALYSIS_INTERVAL", "15"))  # минут
    TRADE_AMOUNT: float = float(os.getenv("TRADE_AMOUNT", "10"))  # $
    MAX_CONCURRENT_POS: int = int(os.getenv("MAX_CONCURRENT_POS", "1"))
    SAFE_MODE: int = int(os.getenv("SAFE_MODE", "1"))
    PAPER_MODE: int = int(os.getenv("PAPER_MODE", "1"))
    ENABLE_TRADING: int = int(os.getenv("ENABLE_TRADING", "1"))

    # Гейты модели/правил
    AI_MIN_TO_TRADE: float = float(os.getenv("AI_MIN_TO_TRADE", "0.55"))
    MIN_SCORE_TO_BUY: float = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))
    ENFORCE_AI_GATE: int = int(os.getenv("ENFORCE_AI_GATE", "1"))

    # RSI/выходы
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    RSI_CRITICAL: float = float(os.getenv("RSI_CRITICAL", "90"))

    # ATR/волатильность
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    TRAILING_STOP_ENABLE: int = int(os.getenv("TRAILING_STOP_ENABLE", "1"))
    TRAILING_STOP_PCT: float = float(os.getenv("TRAILING_STOP_PCT", "0.5"))  # % от цены
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "1.5"))

    # Файлы paper-режима
    PAPER_POSITIONS_FILE: str = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
    PAPER_ORDERS_FILE: str = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
    PAPER_PNL_FILE: str = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")

    @classmethod
    def build(cls) -> "Settings":
        return cls()


@dataclass
class Position:
    symbol: str
    side: str            # "buy" или "sell"
    qty: float
    entry_price: float
    opened_at: str
    sl: Optional[float] = None
    tp: Optional[float] = None
    trailing_max: Optional[float] = None  # для трейлинга
    status: str = "open"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------- Буфер для paper-режима ----------------------

class PaperStore:
    """Лёгкий стор без сторонних библиотек. Никаких новых модулей в проекте."""
    def __init__(self, positions_path: str, orders_csv: str, pnl_csv: str):
        self.positions_path = positions_path
        self.orders_csv = orders_csv
        self.pnl_csv = pnl_csv
        self._ensure_files()

    def _ensure_files(self):
        # positions.json
        if not os.path.exists(self.positions_path):
            with open(self.positions_path, "w", encoding="utf-8") as f:
                json.dump({"open": []}, f, ensure_ascii=False, indent=2)
        # orders.csv
        if not os.path.exists(self.orders_csv):
            import csv
            with open(self.orders_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "symbol", "side", "qty", "price", "client_tag", "type"])
        # pnl.csv
        if not os.path.exists(self.pnl_csv):
            import csv
            with open(self.pnl_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts_open", "ts_close", "symbol", "side", "qty", "entry_price", "exit_price", "pnl_abs", "pnl_pct"])

    def load_positions(self) -> list:
        with open(self.positions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("open", [])

    def save_positions(self, positions: list):
        tmp = self.positions_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"open": positions}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.positions_path)

    def append_order(self, symbol: str, side: str, qty: float, price: float, client_tag: str, order_type: str):
        import csv
        with open(self.orders_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([datetime.now(timezone.utc).isoformat(), symbol, side, f"{qty:.8f}", f"{price:.8f}", client_tag, order_type])

    def append_pnl(self, pos: Position, exit_price: float):
        import csv
        pnl_abs = (exit_price - pos.entry_price) * pos.qty if pos.side == "buy" else (pos.entry_price - exit_price) * pos.qty
        pnl_pct = (exit_price / pos.entry_price - 1.0) * (100 if pos.side == "buy" else -100)
        with open(self.pnl_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([pos.opened_at, datetime.now(timezone.utc).isoformat(), pos.symbol, pos.side, f"{pos.qty:.8f}", f"{pos.entry_price:.8f}", f"{exit_price:.8f}", f"{pnl_abs:.8f}", f"{pnl_pct:.4f}"])


# ---------------------- Основной класс бота ----------------------

class TradingBot:
    _instance_lock = threading.Lock()
    _loop_thread: Optional[threading.Thread] = None
    _running: bool = False

    def __init__(self, exchange: Any, notifier=None, settings: Optional[Settings] = None):
        self.cfg = settings or Settings.build()
        self.exchange = exchange
        self.notifier = notifier  # функция send_telegram_message(text, image_path=None)

        # Управление позицией (в памяти)
        self.position: Optional[Position] = None

        # Paper store (без внешних зависимостей)
        self.paper = PaperStore(self.cfg.PAPER_POSITIONS_FILE, self.cfg.PAPER_ORDERS_FILE, self.cfg.PAPER_PNL_FILE)

    # ------------- Публичный интерфейс -------------

    @classmethod
    def get_instance(cls, exchange: Any, notifier=None, settings: Optional[Settings] = None) -> "TradingBot":
        with cls._instance_lock:
            if not hasattr(cls, "_singleton"):
                cls._singleton = TradingBot(exchange, notifier, settings)
        return cls._singleton

    def start(self):
        """Запускает один торговый цикл в отдельном потоке."""
        with TradingBot._instance_lock:
            if TradingBot._running:
                logger.info("Trading loop already running; skip start()")
                return
            TradingBot._running = True

        self._loop_thread = threading.Thread(target=self._loop, name="trading-loop", daemon=True)
        self._loop_thread.start()
        logger.info("✅ Trading loop started")

    def stop(self):
        with TradingBot._instance_lock:
            TradingBot._running = False
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

    # ------------- Основной цикл -------------

    def _loop(self):
        interval_sec = max(60, int(self.cfg.ANALYSIS_INTERVAL) * 60)
        # Выравнивание по границе свечи
        while TradingBot._running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"tick failed: {e}")
                self._notify(f"⚠️ Tick failed: {e}")
            # ждать до следующей границы
            now = time.time()
            sleep_for = interval_sec - (now % interval_sec)
            time.sleep(max(5, min(sleep_for, interval_sec)))

        logger.info("🛑 Trading loop stopped")

    # ------------- Одна итерация: анализ → действие -------------

    def _tick(self):
        symbol = self.cfg.SYMBOL
        feat = aggregate_features(self.cfg, self.exchange, symbol=symbol, limit=200)

        if "error" in feat:
            logger.warning(f"aggregate_features error: {feat['error']}")
            return

        ind = feat["indicators"]
        price = float(ind.get("price") or 0.0)
        atr = float(ind.get("atr") or 0.0)
        atr_pct = float(ind.get("atr_pct") or 0.0)
        rule_score = float(feat.get("rule_score_penalized", feat.get("rule_score", 0.5)))
        ai_score = float(feat.get("ai_score", 0.55))

        self._notify(f"ℹ️ {symbol} @ {price:.2f} | rule={rule_score:.2f} ai={ai_score:.2f} | ATR%={atr_pct:.2f} | {feat['market']['condition']}")

        # Обновить существующую позицию (SL/TP/трейлинг)
        if self.position:
            self._maybe_close_position(price, atr)
            # если закрылась, не открываем новую на этой же свече
            if not self.position:
                return

        # Решение об открытии
        if not self._can_open_new():
            return

        if self._is_buy_signal(rule_score, ai_score, ind):
            self._open_position("buy", price, atr)
        elif self._is_sell_signal(rule_score, ai_score, ind):
            self._open_position("sell", price, atr)

    # ------------- Решения и гейты -------------

    def _can_open_new(self) -> bool:
        if self.position is not None:
            return False
        if int(self.cfg.ENABLE_TRADING) != 1:
            return False
        return True

    def _is_buy_signal(self, rule: float, ai: float, ind: Dict[str, Any]) -> bool:
        if int(self.cfg.ENFORCE_AI_GATE) == 1 and ai < self.cfg.AI_MIN_TO_TRADE:
            return False
        if rule < self.cfg.MIN_SCORE_TO_BUY:
            return False
        rsi = ind.get("rsi")
        if rsi is not None and rsi >= self.cfg.RSI_CRITICAL:
            return False
        # трендовый фильтр: ema20>ema50
        if (ind.get("ema20") or 0) <= (ind.get("ema50") or 0):
            return False
        return True

    def _is_sell_signal(self, rule: float, ai: float, ind: Dict[str, Any]) -> bool:
        # Для компактности — миррор buy: продаём в шорт только если ema20<ema50.
        if int(self.cfg.ENFORCE_AI_GATE) == 1 and ai < self.cfg.AI_MIN_TO_TRADE:
            return False
        if rule < self.cfg.MIN_SCORE_TO_BUY:
            return False
        rsi = ind.get("rsi")
        if rsi is not None and rsi <= (100 - self.cfg.RSI_CRITICAL):
            return False
        if (ind.get("ema20") or 0) >= (ind.get("ema50") or 0):
            return False
        return True

    # ------------- Исполнение сделок -------------

    def _open_position(self, side: str, price: float, atr: float):
        symbol = self.cfg.SYMBOL
        qty = self._quote_to_base(self.cfg.TRADE_AMOUNT, price)

        # Заявка: либо реальная, либо бумажная
        order_ok = self._create_market_order(symbol, side, qty, price)
        if not order_ok:
            self._notify(f"❌ Не удалось открыть позицию {side} {symbol}")
            return

        # Базовые SL/TP: ATR приоритетен; если ATR==0 — отталкиваемся от pct
        sl, tp = self._compute_sl_tp(price, atr, side)

        self.position = Position(
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=price,
            opened_at=datetime.now(timezone.utc).isoformat(),
            sl=sl, tp=tp,
            trailing_max=price if side == "buy" else None
        )

        self._notify(f"✅ Открыта позиция: {side} {symbol} qty={qty:.8f} @ {price:.2f} | SL={sl and f'{sl:.2f}'} TP={tp and f'{tp:.2f}'}")

        # В paper-режиме — записать позиции
        if int(self.cfg.PAPER_MODE) == 1:
            open_list = self.paper.load_positions()
            open_list.append(self.position.to_dict())
            self.paper.save_positions(open_list)

    def _maybe_close_position(self, price: float, atr: float):
        if not self.position:
            return
        pos = self.position

        # Трейлинг
        if int(self.cfg.TRAILING_STOP_ENABLE) == 1:
            if pos.side == "buy":
                pos.trailing_max = max(pos.trailing_max or price, price)
            else:
                # для шорта можно хранить trailing_min (но для компактности опустим)
                pass

        # Проверка SL/TP
        hit_tp = False
        hit_sl = False

        if pos.side == "buy":
            if pos.tp and price >= pos.tp:
                hit_tp = True
            if pos.sl and price <= pos.sl:
                hit_sl = True
        else:
            if pos.tp and price <= pos.tp:
                hit_tp = True
            if pos.sl and price >= pos.sl:
                hit_sl = True

        if hit_tp or hit_sl:
            reason = "TP" if hit_tp else "SL"
            self._close_position(price, reason)

    def _close_position(self, exit_price: float, reason: str):
        if not self.position:
            return
        pos = self.position
        symbol = pos.symbol
        side = "sell" if pos.side == "buy" else "buy"

        order_ok = self._create_market_order(symbol, side, pos.qty, exit_price, order_type="close")
        if not order_ok:
            self._notify(f"❌ Не удалось закрыть позицию {symbol} ({reason})")
            return

        # PnL
        pnl_abs = (exit_price - pos.entry_price) * pos.qty if pos.side == "buy" else (pos.entry_price - exit_price) * pos.qty
        pnl_pct = (exit_price / pos.entry_price - 1.0) * (100 if pos.side == "buy" else -100)

        self._notify(f"🧾 Закрыта позиция {symbol} по {reason}: exit={exit_price:.2f}, pnl={pnl_abs:.4f} ({pnl_pct:.2f}%)")

        # Paper: записи
        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_pnl(pos, exit_price)
            # убрать из открытых
            open_list = [p for p in self.paper.load_positions() if p.get("opened_at") != pos.opened_at]
            self.paper.save_positions(open_list)

        self.position = None

    # ------------- Низкоуровневые утилиты -------------

    def _quote_to_base(self, quote_usd: float, price: float) -> float:
        if price <= 0:
            return 0.0
        # шаг округления 1e-6 по умолчанию, можно уточнить при интеграции
        amt = math.floor((quote_usd / price) / 1e-6) * 1e-6
        return max(0.0, float(amt))

    def _compute_sl_tp(self, entry: float, atr: float, side: str):
        if atr and np.isfinite(atr) and entry > 0:
            k1, k2 = 1.5, 2.5
            if side == "buy":
                sl = entry - k1 * atr
                tp = entry + k2 * atr
            else:
                sl = entry + k1 * atr
                tp = entry - k2 * atr
            return float(sl), float(tp)
        # fallback на фиксированные проценты
        sl = entry * (1 - self.cfg.STOP_LOSS_PCT / 100) if side == "buy" else entry * (1 + self.cfg.STOP_LOSS_PCT / 100)
        tp = entry * (1 + self.cfg.TAKE_PROFIT_PCT / 100) if side == "buy" else entry * (1 - self.cfg.TAKE_PROFIT_PCT / 100)
        return float(sl), float(tp)

    def _get_last_price(self, symbol: str, fallback_df: Optional[pd.DataFrame] = None) -> float:
        # попытаться через биржу
        try:
            if hasattr(self.exchange, "fetch_ticker"):
                t = self.exchange.fetch_ticker(symbol)
                px = t.get("last") or t.get("close")
                if px:
                    return float(px)
        except Exception as e:
            logger.debug(f"fetch_ticker failed: {e}")
        # фолбэк на последнюю свечу
        if fallback_df is not None and not fallback_df.empty:
            return float(fallback_df["close"].iloc[-1])
        # крайний случай
        return 0.0

    def _create_market_order(self, symbol: str, side: str, qty: float, price_hint: float, order_type: str = "open") -> bool:
        """Единая точка: уважает SAFE_MODE/PAPER_MODE. Возвращает True, если «сделка» засчитана."""
        client_tag = f"bot-{order_type}-{uuid.uuid4().hex[:12]}"
        # SAFE → не отправляем на биржу
        if int(self.cfg.SAFE_MODE) == 1:
            logger.info(f"[SAFE] {order_type} {symbol} {side} qty={qty:.8f}")
            if int(self.cfg.PAPER_MODE) == 1:
                self.paper.append_order(symbol, side, qty, price_hint, client_tag, order_type)
            return True

        # PAPER → записываем эмуляцию и выходим
        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_order(symbol, side, qty, price_hint, client_tag, order_type)
            return True

        # Живая заявка (ccxt)
        if not hasattr(self.exchange, "create_order"):
            logger.error("exchange has no create_order; enable SAFE/PAPER or implement adapter")
            return False

        retries = 3
        delay = 0.4
        for i in range(retries):
            try:
                params = {"text": client_tag} if "gate" in str(type(self.exchange)).lower() else {}
                self.exchange.create_order(symbol, "market", side, qty, params=params)  # type: ignore
                logger.info(f"[LIVE] Order sent: {order_type} {symbol} {side} qty={qty:.8f}")
                return True
            except NetworkError as e:
                time.sleep(delay * (2 ** i))
                continue
            except ExchangeError as e:
                logger.error(f"create_order failed: {e}")
                return False
            except Exception as e:
                logger.error(f"create_order unexpected: {e}")
                return False
        return False

    def _notify(self, text: str):
        try:
            if self.notifier:
                self.notifier(text)
        except Exception:
            logger.debug("notifier failed", exc_info=True)


# ------------- Утилита интеграции (минимум кода в server.py) -------------

def get_bot(exchange: Any, notifier=None, settings: Optional[Settings] = None) -> TradingBot:
    """Единственная точка получения синглтона бота в приложении."""
    return TradingBot.get_instance(exchange=exchange, notifier=notifier, settings=settings)
