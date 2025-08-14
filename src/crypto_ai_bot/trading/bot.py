
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
crypto_ai_bot/trading/bot.py
Centralized Settings version — вся конфигурация читается один раз из ENV.
Остальной код использует только cfg (никаких os.getenv вне Settings).
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
    import ccxt
    from ccxt.base.errors import NetworkError, ExchangeError
except Exception:
    ccxt = None
    class NetworkError(Exception): ...
    class ExchangeError(Exception): ...

from crypto_ai_bot.trading.signals.signal_aggregator import aggregate_features

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))


# ---------------- Settings (единственная точка чтения ENV) ----------------

@dataclass
class Settings:
    # Core
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = int(os.getenv("ANALYSIS_INTERVAL", "15"))  # minutes
    ENABLE_TRADING: int = int(os.getenv("ENABLE_TRADING", "1"))
    SAFE_MODE: int = int(os.getenv("SAFE_MODE", "1"))
    PAPER_MODE: int = int(os.getenv("PAPER_MODE", "1"))
    TRADE_AMOUNT: float = float(os.getenv("TRADE_AMOUNT", "10"))
    MAX_CONCURRENT_POS: int = int(os.getenv("MAX_CONCURRENT_POS", "1"))

    # Data / Limits
    AGGREGATOR_LIMIT: int = int(os.getenv("AGGREGATOR_LIMIT", "200"))
    OHLCV_LIMIT: int = int(os.getenv("OHLCV_LIMIT", "200"))

    # Gates / Scoring
    AI_FAILOVER_SCORE: float = float(os.getenv("AI_FAILOVER_SCORE", "0.55"))
    AI_MIN_TO_TRADE: float = float(os.getenv("AI_MIN_TO_TRADE", "0.55"))
    ENFORCE_AI_GATE: int = int(os.getenv("ENFORCE_AI_GATE", "1"))
    MIN_SCORE_TO_BUY: float = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))

    # Risk / Volatility
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "1.5"))
    TRAILING_STOP_ENABLE: int = int(os.getenv("TRAILING_STOP_ENABLE", "1"))
    TRAILING_STOP_PCT: float = float(os.getenv("TRAILING_STOP_PCT", "0.5"))

    # RSI
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    RSI_CRITICAL: float = float(os.getenv("RSI_CRITICAL", "90"))

    # Context penalties
    USE_CONTEXT_PENALTIES: int = int(os.getenv("USE_CONTEXT_PENALTIES", "1"))
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

    # Trading hours (optional window)
    TRADING_HOUR_START: int = int(os.getenv("TRADING_HOUR_START", "0"))
    TRADING_HOUR_END: int = int(os.getenv("TRADING_HOUR_END", "24"))

    # Paper store
    PAPER_POSITIONS_FILE: str = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
    PAPER_ORDERS_FILE: str = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
    PAPER_PNL_FILE: str = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")

    @classmethod
    def build(cls) -> "Settings":
        return cls()


# ---------------- Position state & Paper store ----------------

@dataclass
class Position:
    symbol: str
    side: str
    qty: float
    entry_price: float
    opened_at: str
    sl: Optional[float] = None
    tp: Optional[float] = None
    trailing_max: Optional[float] = None
    status: str = "open"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
                csv.writer(f).writerow(["ts","symbol","side","qty","price","client_tag","type"])
        if not os.path.exists(self.pnl_csv):
            import csv
            with open(self.pnl_csv, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["ts_open","ts_close","symbol","side","qty","entry_price","exit_price","pnl_abs","pnl_pct"])

    def load_positions(self) -> list:
        with open(self.positions_path, "r", encoding="utf-8") as f:
            return json.load(f).get("open", [])

    def save_positions(self, positions: list):
        tmp = self.positions_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"open": positions}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.positions_path)

    def append_order(self, symbol: str, side: str, qty: float, price: float, client_tag: str, order_type: str):
        import csv
        with open(self.orders_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(), symbol, side, f"{qty:.8f}", f"{price:.8f}", client_tag, order_type])

    def append_pnl(self, pos: Position, exit_price: float):
        import csv
        pnl_abs = (exit_price - pos.entry_price) * pos.qty if pos.side == "buy" else (pos.entry_price - exit_price) * pos.qty
        pnl_pct = (exit_price / pos.entry_price - 1.0) * (100 if pos.side == "buy" else -100)
        with open(self.pnl_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([pos.opened_at, datetime.now(timezone.utc).isoformat(), pos.symbol, pos.side, f"{pos.qty:.8f}", f"{pos.entry_price:.8f}", f"{exit_price:.8f}", f"{pnl_abs:.8f}", f"{pnl_pct:.4f}"])


# ---------------- Trading bot core ----------------

class TradingBot:
    _instance_lock = threading.Lock()
    _loop_thread: Optional[threading.Thread] = None
    _running: bool = False

    def __init__(self, exchange: Any, notifier=None, settings: Optional[Settings] = None):
        self.cfg = settings or Settings.build()
        self.exchange = exchange
        self.notifier = notifier
        self.position: Optional[Position] = None
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

    def _within_trading_hours(self) -> bool:
        try:
            import datetime as _dt
            now = _dt.datetime.utcnow().hour
            return self.cfg.TRADING_HOUR_START <= now < self.cfg.TRADING_HOUR_END
        except Exception:
            return True

    def _loop(self):
        interval_sec = max(60, int(self.cfg.ANALYSIS_INTERVAL) * 60)
        while TradingBot._running:
            try:
                if self._within_trading_hours():
                    self._tick()
                else:
                    self._notify("⏸ Вне торгового окна")
            except Exception as e:
                logger.exception(f"tick failed: {e}")
                self._notify(f"⚠️ Tick failed: {e}")
            now = time.time()
            sleep_for = interval_sec - (now % interval_sec)
            time.sleep(max(5, min(sleep_for, interval_sec)))
        logger.info("🛑 Trading loop stopped")

    def _tick(self):
        symbol = self.cfg.SYMBOL
        feat = aggregate_features(self.cfg, self.exchange, symbol=symbol, limit=self.cfg.AGGREGATOR_LIMIT)
        if "error" in feat:
            logger.warning(f"aggregate_features error: {feat['error']}")
            return

        ind = feat["indicators"]
        price = float(ind.get("price") or 0.0)
        atr = float(ind.get("atr") or 0.0)
        atr_pct = float(ind.get("atr_pct") or 0.0)
        rule_score = float(feat.get("rule_score_penalized", feat.get("rule_score", self.cfg.AI_FAILOVER_SCORE)))
        ai_score = float(feat.get("ai_score", self.cfg.AI_FAILOVER_SCORE))

        self._notify(f"ℹ️ {symbol} @ {price:.2f} | rule={rule_score:.2f} ai={ai_score:.2f} | ATR%={atr_pct:.2f} | {feat['market']['condition']}")

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

    def _open_position(self, side: str, price: float, atr: float):
        symbol = self.cfg.SYMBOL
        qty = self._quote_to_base(self.cfg.TRADE_AMOUNT, price)
        order_ok = self._create_market_order(symbol, side, qty, price)
        if not order_ok:
            self._notify(f"❌ Не удалось открыть позицию {side} {symbol}")
            return
        sl, tp = self._compute_sl_tp(price, atr, side)
        self.position = Position(
            symbol=symbol, side=side, qty=qty, entry_price=price,
            opened_at=datetime.now(timezone.utc).isoformat(),
            sl=sl, tp=tp, trailing_max=price if side == "buy" else None
        )
        self._notify(f"✅ Открыта позиция: {side} {symbol} qty={qty:.8f} @ {price:.2f} | SL={sl and f'{sl:.2f}'} TP={tp and f'{tp:.2f}'}")
        if int(self.cfg.PAPER_MODE) == 1:
            open_list = self.paper.load_positions()
            open_list.append(self.position.to_dict())
            self.paper.save_positions(open_list)

    def _maybe_close_position(self, price: float, atr: float):
        if not self.position:
            return
        pos = self.position
        if int(self.cfg.TRAILING_STOP_ENABLE) == 1 and pos.side == "buy":
            pos.trailing_max = max(pos.trailing_max or price, price)

        hit_tp = hit_sl = False
        if pos.side == "buy":
            hit_tp = bool(pos.tp and price >= pos.tp)
            hit_sl = bool(pos.sl and price <= pos.sl)
        else:
            hit_tp = bool(pos.tp and price <= pos.tp)
            hit_sl = bool(pos.sl and price >= pos.sl)

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

        pnl_abs = (exit_price - pos.entry_price) * pos.qty if pos.side == "buy" else (pos.entry_price - exit_price) * pos.qty
        pnl_pct = (exit_price / pos.entry_price - 1.0) * (100 if pos.side == "buy" else -100)
        self._notify(f"🧾 Закрыта позиция {symbol} по {reason}: exit={exit_price:.2f}, pnl={pnl_abs:.4f} ({pnl_pct:.2f}%)")

        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_pnl(pos, exit_price)
            open_list = [p for p in self.paper.load_positions() if p.get("opened_at") != pos.opened_at]
            self.paper.save_positions(open_list)

        self.position = None

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

    def _get_last_price(self, symbol: str, fallback_df: Optional[pd.DataFrame] = None) -> float:
        try:
            if hasattr(self.exchange, "fetch_ticker"):
                t = self.exchange.fetch_ticker(symbol)
                px = t.get("last") or t.get("close")
                if px: return float(px)
        except Exception as e:
            logger.debug(f"fetch_ticker failed: {e}")
        if fallback_df is not None and not fallback_df.empty:
            return float(fallback_df["close"].iloc[-1])
        return 0.0

    def _create_market_order(self, symbol: str, side: str, qty: float, price_hint: float, order_type: str = "open") -> bool:
        client_tag = f"bot-{order_type}-{uuid.uuid4().hex[:12]}"
        if int(self.cfg.SAFE_MODE) == 1:
            logger.info(f"[SAFE] {order_type} {symbol} {side} qty={qty:.8f}")
            if int(self.cfg.PAPER_MODE) == 1:
                self.paper.append_order(symbol, side, qty, price_hint, client_tag, order_type)
            return True
        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_order(symbol, side, qty, price_hint, client_tag, order_type)
            return True
        if not hasattr(self.exchange, "create_order"):
            logger.error("exchange has no create_order; enable SAFE/PAPER or implement adapter")
            return False

        retries = 3; delay = 0.4
        for i in range(retries):
            try:
                params = {"text": client_tag} if "gate" in str(type(self.exchange)).lower() else {}
                self.exchange.create_order(symbol, "market", side, qty, params=params)  # type: ignore
                logger.info(f"[LIVE] Order sent: {order_type} {symbol} {side} qty={qty:.8f}")
                return True
            except NetworkError:
                time.sleep(delay * (2 ** i)); continue
            except ExchangeError as e:
                logger.error(f"create_order failed: {e}"); return False
            except Exception as e:
                logger.error(f"create_order unexpected: {e}"); return False
        return False

    def _notify(self, text: str):
        try:
            if self.notifier: self.notifier(text)
        except Exception:
            logger.debug("notifier failed", exc_info=True)


def get_bot(exchange: Any, notifier=None, settings: Optional[Settings] = None) -> TradingBot:
    return TradingBot.get_instance(exchange=exchange, notifier=notifier, settings=settings)
