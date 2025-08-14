
# -*- coding: utf-8 -*-
from __future__ import annotations

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

from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

# ---------------------- Централизованный Settings ----------------------

@dataclass
class Settings:
    # Основные
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = int(os.getenv("ANALYSIS_INTERVAL", "15"))  # минут
    ENABLE_TRADING: int = int(os.getenv("ENABLE_TRADING", "1"))
    SAFE_MODE: int = int(os.getenv("SAFE_MODE", "1"))
    PAPER_MODE: int = int(os.getenv("PAPER_MODE", "1"))
    TRADE_AMOUNT: float = float(os.getenv("TRADE_AMOUNT", "10"))
    MAX_CONCURRENT_POS: int = int(os.getenv("MAX_CONCURRENT_POS", "1"))
    OHLCV_LIMIT: int = int(os.getenv("OHLCV_LIMIT", "200"))
    AGGREGATOR_LIMIT: int = int(os.getenv("AGGREGATOR_LIMIT", "200"))

    # Гейты/скоринг
    AI_FAILOVER_SCORE: float = float(os.getenv("AI_FAILOVER_SCORE", "0.55"))
    AI_MIN_TO_TRADE: float = float(os.getenv("AI_MIN_TO_TRADE", "0.55"))
    ENFORCE_AI_GATE: int = int(os.getenv("ENFORCE_AI_GATE", "1"))
    MIN_SCORE_TO_BUY: float = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))

    # RSI/выходы
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    RSI_CRITICAL: float = float(os.getenv("RSI_CRITICAL", "90"))

    # ATR/волатильность
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    TRAILING_STOP_ENABLE: int = int(os.getenv("TRAILING_STOP_ENABLE", "1"))
    TRAILING_STOP_PCT: float = float(os.getenv("TRAILING_STOP_PCT", "0.5"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "1.5"))

    # Контекстные штрафы (опционально)
    USE_CONTEXT_PENALTIES: int = int(os.getenv("USE_CONTEXT_PENALTIES", "0"))
    CTX_BTC_DOM_ALTS_ONLY: int = int(os.getenv("CTX_BTC_DOM_ALTS_ONLY", "1"))
    CTX_BTC_DOM_THRESH: float = float(os.getenv("CTX_BTC_DOM_THRESH", "52.0"))
    CTX_BTC_DOM_PENALTY: float = float(os.getenv("CTX_BTC_DOM_PENALTY", "-0.05"))

    CTX_DXY_DELTA_THRESH: float = float(os.getenv("CTX_DXY_DELTA_THRESH", "0.5"))
    CTX_DXY_PENALTY: float = float(os.getenv("CTX_DXY_PENALTY", "-0.05"))

    CTX_FNG_OVERHEATED: float = float(os.getenv("CTX_FNG_OVERHEATED", "75"))
    CTX_FNG_UNDERSHOOT: float = float(os.getenv("CTX_FNG_UNDERSHOOT", "25"))
    CTX_FNG_PENALTY: float = float(os.getenv("CTX_FNG_PENALTY", "-0.05"))
    CTX_FNG_BONUS: float = float(os.getenv("CTX_FNG_BONUS", "0.03"))

    CTX_SCORE_CLAMP_MIN: float = float(os.getenv("CTX_SCORE_CLAMP_MIN", "0.0"))
    CTX_SCORE_CLAMP_MAX: float = float(os.getenv("CTX_SCORE_CLAMP_MAX", "1.0"))

    # Торговые часы (UTC)
    TRADING_HOUR_START: int = int(os.getenv("TRADING_HOUR_START", "0"))
    TRADING_HOUR_END: int = int(os.getenv("TRADING_HOUR_END", "24"))

    # Файлы paper-режима
    PAPER_POSITIONS_FILE: str = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
    PAPER_ORDERS_FILE: str = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
    PAPER_PNL_FILE: str = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")

    @classmethod
    def build(cls) -> "Settings":
        return cls()

# ---------------------- Позиция и стор для paper ----------------------

class Position(dict):
    pass

class PaperStore:
    def __init__(self, positions_path: str, orders_csv: str, pnl_csv: str):
        self.positions_path = positions_path
        self.orders_csv = orders_csv
        self.pnl_csv = pnl_csv
        self._ensure_files()

    def _ensure_files(self):
        if not os.path.exists(self.positions_path):
            with open(self.positions_path, "w", encoding="utf-8") as f:
                json.dump({"open": []}, f, ensure_ascii=False, indent=2)
        if not os.path.exists(self.orders_csv):
            import csv
            with open(self.orders_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["ts","symbol","side","qty","price","client_tag","type"])
        if not os.path.exists(self.pnl_csv):
            import csv
            with open(self.pnl_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["ts_open","ts_close","symbol","side","qty","entry_price","exit_price","pnl_abs","pnl_pct"])

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
            w = csv.writer(f); w.writerow([datetime.now(timezone.utc).isoformat(), symbol, side, f"{qty:.8f}", f"{price:.8f}", client_tag, order_type])

    def append_pnl(self, pos: dict, exit_price: float):
        import csv
        qty = float(pos.get("qty", 0.0))
        entry = float(pos.get("entry_price", 0.0))
        side = pos.get("side")
        pnl_abs = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
        pnl_pct = (exit_price / entry - 1.0) * (100 if side == "buy" else -100) if entry > 0 else 0.0
        with open(self.pnl_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow([pos.get("opened_at"), datetime.now(timezone.utc).isoformat(), pos.get("symbol"), side, f"{qty:.8f}", f"{entry:.8f}", f"{exit_price:.8f}", f"{pnl_abs:.8f}", f"{pnl_pct:.4f}"])

# ---------------------- Торговый бот ----------------------

class TradingBot:
    _instance_lock = threading.Lock()
    _loop_thread: Optional[threading.Thread] = None
    _running: bool = False

    def __init__(self, exchange: Any, notifier=None, settings: Optional[Settings] = None):
        self.cfg = settings or Settings.build()
        self.exchange = exchange
        self.notifier = notifier
        self.position: Optional[dict] = None
        self.paper = PaperStore(self.cfg.PAPER_POSITIONS_FILE, self.cfg.PAPER_ORDERS_FILE, self.cfg.PAPER_PNL_FILE)

    @classmethod
    def get_instance(cls, exchange: Any, notifier=None, settings: Optional[Settings] = None) -> "TradingBot":
        with cls._instance_lock:
            if not hasattr(cls, "_singleton"):
                cls._singleton = TradingBot(exchange, notifier, settings)
        return cls._singleton

    def start(self):
        with TradingBot._instance_lock:
            if TradingBot._running:
                logger.info("Trading loop already running"); return
            TradingBot._running = True
        self._loop_thread = threading.Thread(target=self._loop, name="trading-loop", daemon=True)
        self._loop_thread.start()
        logger.info("✅ Trading loop started")

    def stop(self):
        with TradingBot._instance_lock:
            TradingBot._running = False
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

    # ---------------------- цикл ----------------------
    def _loop(self):
        interval_sec = max(60, int(self.cfg.ANALYSIS_INTERVAL) * 60)
        while TradingBot._running:
            try:
                # торговые часы (UTC)
                hour = datetime.now(timezone.utc).hour
                if not (int(self.cfg.TRADING_HOUR_START) <= hour < int(self.cfg.TRADING_HOUR_END)):
                    self._notify(f"⏸ Outside trading hours UTC {self.cfg.TRADING_HOUR_START}-{self.cfg.TRADING_HOUR_END}")
                else:
                    self._tick()
            except Exception as e:
                logger.exception(f"tick failed: {e}")
                self._notify(f"⚠️ Tick failed: {e}")
            # выравнивание по границе
            now = time.time()
            sleep_for = interval_sec - (now % interval_sec)
            time.sleep(max(5, min(sleep_for, interval_sec)))
        logger.info("🛑 Trading loop stopped")

    # ---------------------- итерация ----------------------
    def _tick(self):
        symbol = self.cfg.SYMBOL
        feat = aggregate_features(self.cfg, self.exchange, symbol=symbol, limit=int(self.cfg.AGGREGATOR_LIMIT))
        if "error" in feat:
            logger.warning(f"aggregate_features error: {feat['error']}"); return

        ind = feat.get("indicators", {})
        price = float(ind.get("price") or 0.0)
        atr = float(ind.get("atr") or 0.0)
        atr_pct = float(ind.get("atr_pct") or 0.0)
        rule_score = float(feat.get("rule_score_penalized", feat.get("rule_score", 0.5)))
        ai_score = float(feat.get("ai_score", self.cfg.AI_FAILOVER_SCORE))

        cond = feat.get("market", {}).get("condition", "neutral")
        self._notify(f"ℹ️ {symbol} @ {price:.2f} | rule={rule_score:.2f} ai={ai_score:.2f} | ATR%={atr_pct:.2f} | {cond}")

        # обновить открытую
        if self.position:
            self._maybe_close_position(price, atr)
            if not self.position:
                return

        if not self._can_open_new():
            return

        if self._is_buy_signal(rule_score, ai_score, ind):
            self._open_position("buy", price, atr)
        elif self._is_sell_signal(rule_score, ai_score, ind):
            self._open_position("sell", price, atr)

    # ---------------------- гейты ----------------------
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
        if (ind.get("ema20") or 0) <= (ind.get("ema50") or 0):
            return False
        return True

    def _is_sell_signal(self, rule: float, ai: float, ind: Dict[str, Any]) -> bool:
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

    # ---------------------- исполнение ----------------------
    def _open_position(self, side: str, price: float, atr: float):
        symbol = self.cfg.SYMBOL
        qty = self._quote_to_base(self.cfg.TRADE_AMOUNT, price)
        order_ok = self._create_market_order(symbol, side, qty, price)
        if not order_ok:
            self._notify(f"❌ Не удалось открыть позицию {side} {symbol}")
            return

        sl, tp = self._compute_sl_tp(price, atr, side)
        self.position = {
            "symbol": symbol, "side": side, "qty": qty, "entry_price": price,
            "opened_at": datetime.now(timezone.utc).isoformat(), "sl": sl, "tp": tp,
            "trailing_max": price if side == "buy" else None, "status": "open",
        }
        self._notify(f"✅ Открыта позиция: {side} {symbol} qty={qty:.8f} @ {price:.2f} | SL={sl and f'{sl:.2f}'} TP={tp and f'{tp:.2f}'}")

        if int(self.cfg.PAPER_MODE) == 1:
            open_list = self.paper.load_positions(); open_list.append(self.position); self.paper.save_positions(open_list)

    def _maybe_close_position(self, price: float, atr: float):
        if not self.position: return
        pos = self.position

        # трейлинг
        if int(self.cfg.TRAILING_STOP_ENABLE) == 1 and pos.get("side") == "buy":
            pos["trailing_max"] = max(pos.get("trailing_max") or price, price)

        hit_tp = hit_sl = False
        if pos.get("side") == "buy":
            if pos.get("tp") and price >= pos["tp"]: hit_tp = True
            if pos.get("sl") and price <= pos["sl"]: hit_sl = True
        else:
            if pos.get("tp") and price <= pos["tp"]: hit_tp = True
            if pos.get("sl") and price >= pos["sl"]: hit_sl = True

        if hit_tp or hit_sl:
            self._close_position(price, "TP" if hit_tp else "SL")

    def _close_position(self, exit_price: float, reason: str):
        if not self.position: return
        pos = self.position
        symbol = pos["symbol"]
        side = "sell" if pos["side"] == "buy" else "buy"

        order_ok = self._create_market_order(symbol, side, pos["qty"], exit_price, order_type="close")
        if not order_ok:
            self._notify(f"❌ Не удалось закрыть позицию {symbol} ({reason})"); return

        qty = float(pos["qty"]); entry = float(pos["entry_price"])
        pnl_abs = (exit_price - entry) * qty if pos["side"] == "buy" else (entry - exit_price) * qty
        pnl_pct = (exit_price / entry - 1.0) * (100 if pos["side"] == "buy" else -100) if entry > 0 else 0.0
        self._notify(f"🧾 Закрыта позиция {symbol} по {reason}: exit={exit_price:.2f}, pnl={pnl_abs:.4f} ({pnl_pct:.2f}%)")

        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_pnl(pos, exit_price)
            open_list = [p for p in self.paper.load_positions() if p.get("opened_at") != pos.get("opened_at")]
            self.paper.save_positions(open_list)

        self.position = None

    # ---------------------- утилиты ----------------------
    def _quote_to_base(self, quote_usd: float, price: float) -> float:
        if price <= 0: return 0.0
        amt = math.floor((quote_usd / price) / 1e-6) * 1e-6
        return max(0.0, float(amt))

    def _compute_sl_tp(self, entry: float, atr: float, side: str):
        if atr and np.isfinite(atr) and entry > 0:
            k1, k2 = 1.5, 2.5
            if side == "buy":
                sl = entry - k1 * atr; tp = entry + k2 * atr
            else:
                sl = entry + k1 * atr; tp = entry - k2 * atr
            return float(sl), float(tp)
        sl = entry * (1 - self.cfg.STOP_LOSS_PCT / 100) if side == "buy" else entry * (1 + self.cfg.STOP_LOSS_PCT / 100)
        tp = entry * (1 + self.cfg.TAKE_PROFIT_PCT / 100) if side == "buy" else entry * (1 - self.cfg.TAKE_PROFIT_PCT / 100)
        return float(sl), float(tp)

    def _create_market_order(self, symbol: str, side: str, qty: float, price_hint: float, order_type: str = "open") -> bool:
        client_tag = f"bot-{order_type}-{uuid.uuid4().hex[:12]}"
        if int(self.cfg.SAFE_MODE) == 1 or int(self.cfg.PAPER_MODE) == 1:
            if int(self.cfg.PAPER_MODE) == 1:
                self.paper.append_order(symbol, side, qty, price_hint, client_tag, order_type)
            logger.info(f"[SIM] {order_type} {symbol} {side} {qty:.8f} @~{price_hint:.2f}")
            return True

        if not hasattr(self.exchange, "create_order"):
            logger.error("exchange has no create_order; enable SAFE/PAPER or implement adapter")
            return False

        try:
            params = {"text": client_tag}
            self.exchange.create_order(symbol, "market", side, qty, params=params)  # type: ignore
            logger.info(f"[LIVE] order sent {order_type} {symbol} {side} {qty:.8f}")
            return True
        except Exception as e:
            logger.error(f"create_order failed: {e}")
            return False

    def _notify(self, text: str):
        try:
            if self.notifier: self.notifier(text)
        except Exception:
            logger.debug("notifier failed", exc_info=True)

# удобная точка входа
def get_bot(exchange: Any, notifier=None, settings: Optional[Settings] = None) -> TradingBot:
    return TradingBot.get_instance(exchange=exchange, notifier=notifier, settings=settings)
