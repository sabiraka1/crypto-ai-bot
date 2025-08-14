# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import math
import uuid
import json
import threading
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

# features & policies (fixed import path вЂ“ no fallbacks)
from crypto_ai_bot.core.signals.aggregator import aggregate_features
from crypto_ai_bot.trading.signals.score_fusion import fuse_scores
from crypto_ai_bot.trading.crypto_ai_bot.core.signals.validator import validate_features
from crypto_ai_bot.trading.crypto_ai_bot.core.signals.policy import decide as policy_decide

# risk pipeline (fixed import path вЂ“ no fallbacks)
from crypto_ai_bot.trading import risk as riskmod

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))

@dataclass
class Settings:
    SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "15m")
    ANALYSIS_INTERVAL: int = int(os.getenv("ANALYSIS_INTERVAL", "15"))
    ENABLE_TRADING: int = int(os.getenv("ENABLE_TRADING", "1"))
    SAFE_MODE: int = int(os.getenv("SAFE_MODE", "1"))
    PAPER_MODE: int = int(os.getenv("PAPER_MODE", "1"))
    TRADE_AMOUNT: float = float(os.getenv("TRADE_AMOUNT", "10"))
    MAX_CONCURRENT_POS: int = int(os.getenv("MAX_CONCURRENT_POS", "1"))
    OHLCV_LIMIT: int = int(os.getenv("OHLCV_LIMIT", "200"))
    AGGREGATOR_LIMIT: int = int(os.getenv("AGGREGATOR_LIMIT", "200"))

    # Risk gates
    MAX_SPREAD_BPS: float = float(os.getenv("MAX_SPREAD_BPS", "15"))
    MIN_24H_VOLUME_USD: float = float(os.getenv("MIN_24H_VOLUME_USD", "1000000"))

    # Scoring
    AI_ENABLE: int = int(os.getenv("AI_ENABLE", "1"))
    AI_FAILOVER_SCORE: float = float(os.getenv("AI_FAILOVER_SCORE", "0.55"))
    AI_MIN_TO_TRADE: float = float(os.getenv("AI_MIN_TO_TRADE", "0.55"))
    ENFORCE_AI_GATE: int = int(os.getenv("ENFORCE_AI_GATE", "1"))
    MIN_SCORE_TO_BUY: float = float(os.getenv("MIN_SCORE_TO_BUY", "0.65"))
    RULE_WEIGHT: float = float(os.getenv("RULE_WEIGHT", "0.6"))
    AI_WEIGHT: float = float(os.getenv("AI_WEIGHT", "0.4"))

    # RSI/ATR
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    RSI_CRITICAL: float = float(os.getenv("RSI_CRITICAL", "90"))
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    TRAILING_STOP_ENABLE: int = int(os.getenv("TRAILING_STOP_ENABLE", "1"))
    TRAILING_STOP_PCT: float = float(os.getenv("TRAILING_STOP_PCT", "0.5"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "1.5"))
    RISK_ATR_METHOD: str = os.getenv("RISK_ATR_METHOD", "ewm")

    # Hours
    TRADING_HOUR_START: int = int(os.getenv("TRADING_HOUR_START", "0"))
    TRADING_HOUR_END: int = int(os.getenv("TRADING_HOUR_END", "24"))

    # Paper files
    PAPER_POSITIONS_FILE: str = os.getenv("PAPER_POSITIONS_FILE", "paper_positions.json")
    PAPER_ORDERS_FILE: str = os.getenv("PAPER_ORDERS_FILE", "paper_orders.csv")
    PAPER_PNL_FILE: str = os.getenv("PAPER_PNL_FILE", "paper_pnl.csv")

    @classmethod
    def build(cls) -> "Settings":
        return cls()

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
        logger.info("вњ… Trading loop started")

    def stop(self):
        with TradingBot._instance_lock:
            TradingBot._running = False
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)

    # ---------------------- loop ----------------------
    def _loop(self):
        interval_sec = max(60, int(self.cfg.ANALYSIS_INTERVAL) * 60)
        while TradingBot._running:
            try:
                hour = datetime.now(timezone.utc).hour
                if not (int(self.cfg.TRADING_HOUR_START) <= hour < int(self.cfg.TRADING_HOUR_END)):
                    self._notify(f"вЏё Outside trading hours UTC {self.cfg.TRADING_HOUR_START}-{self.cfg.TRADING_HOUR_END}")
                else:
                    self._tick()
            except Exception as e:
                logger.exception(f"tick failed: {e}")
                self._notify(f"вљ пёЏ Tick failed: {e}")
            now = time.time()
            sleep_for = interval_sec - (now % interval_sec)
            time.sleep(max(5, min(sleep_for, interval_sec)))
        logger.info("рџ›‘ Trading loop stopped")

    # ---------------------- iteration ----------------------
    def _tick(self):
        symbol = self.cfg.SYMBOL
        feat = aggregate_features(self.cfg, self.exchange, symbol=symbol, limit=int(self.cfg.AGGREGATOR_LIMIT))
        if isinstance(feat, dict) and "error" in feat:
            logger.warning(f"aggregate_features error: {feat['error']}"); return

        ok, problems = validate_features(self.cfg, feat)
        if not ok:
            self._notify("вќЊ Feature validation: " + "; ".join(problems)); return

        ind = feat.get("indicators", {})
        price = float(ind.get("price") or 0.0)
        atr   = float(ind.get("atr") or 0.0)

        # AI score: РµСЃР»Рё РјРѕРґРµР»Рё РЅРµС‚, Р±РµСЂС‘Рј failover РёР· cfg
        ai_score = float(getattr(self.cfg, "AI_FAILOVER_SCORE", 0.55))
        fused = fuse_scores(self.cfg, float(feat.get("rule_score_penalized", feat.get("rule_score", 0.5))), ai_score)

        decision = policy_decide(self.cfg, feat, fused)
        action = decision.get("action")
        reason = str(decision.get("reason", ""))
        score  = float(decision.get("score") or 0.0)

        self._notify(f"в„№пёЏ {symbol} | action={action} score={score:.2f} | {reason}")

        if not self._can_open_new():
            return
        if action in ("buy", "sell"):
            self._open_position(action, price, atr)

    # ---------------------- gates ----------------------
    def _can_open_new(self) -> bool:
        if self.position is not None:
            return False
        if int(self.cfg.ENABLE_TRADING) != 1:
            return False
        return True

    # ---------------------- execution ----------------------
    def _open_position(self, side: str, price: float, atr: float):
        if riskmod is not None:
            ok, reason = riskmod.validate_open(self.cfg, self.exchange, self.cfg.SYMBOL)
            if not ok:
                self._notify(f"в›” Order blocked: {reason}")
                return

        symbol = self.cfg.SYMBOL
        qty = self._quote_to_base(self.cfg.TRADE_AMOUNT, price)
        order_ok = self._create_market_order(symbol, side, qty, price)
        if not order_ok:
            self._notify(f"вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ РїРѕР·РёС†РёСЋ {side} {symbol}")
            return

        sl, tp = self._compute_sl_tp(price, atr, side)
        self.position = {
            "symbol": symbol, "side": side, "qty": qty, "entry_price": price,
            "opened_at": datetime.now(timezone.utc).isoformat(), "sl": sl, "tp": tp,
            "trailing_max": price if side == "buy" else None, "status": "open",
        }
        self._notify(f"вњ… РћС‚РєСЂС‹С‚Р° РїРѕР·РёС†РёСЏ: {side} {symbol} qty={qty:.8f} @ {price:.2f} | SL={sl and f'{sl:.2f}'} TP={tp and f'{tp:.2f}'}")

        if int(self.cfg.PAPER_MODE) == 1:
            open_list = self.paper.load_positions(); open_list.append(self.position); self.paper.save_positions(open_list)

    def _maybe_close_position(self, price: float, atr: float):
        if not self.position: return
        pos = self.position

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
            self._notify(f"вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РєСЂС‹С‚СЊ РїРѕР·РёС†РёСЋ {symbol} ({reason})"); return

        qty = float(pos["qty"]); entry = float(pos["entry_price"])
        pnl_abs = (exit_price - entry) * qty if pos["side"] == "buy" else (entry - exit_price) * qty
        pnl_pct = (exit_price / entry - 1.0) * (100 if pos["side"] == "buy" else -100) if entry > 0 else 0.0
        self._notify(f"рџ§ѕ Р—Р°РєСЂС‹С‚Р° РїРѕР·РёС†РёСЏ {symbol} РїРѕ {reason}: exit={exit_price:.2f}, pnl={pnl_abs:.4f} ({pnl_pct:.2f}%)")

        if int(self.cfg.PAPER_MODE) == 1:
            self.paper.append_pnl(pos, exit_price)
            open_list = [p for p in self.paper.load_positions() if p.get("opened_at") != pos.get("opened_at")]
            self.paper.save_positions(open_list)

        self.position = None

    # ---------------------- utils ----------------------
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
        tp = entry * (1 + self.cfg.TAKE_PROIT_PCT / 100) if side == "buy" else entry * (1 - self.cfg.TAKE_PROFIT_PCT / 100)
        # fix typo if any
        if not isinstance(tp, float):
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

    # ========= Telegram public API =========
    def request_market_order(self, side: str, amount: float, *, source: str = "telegram") -> dict:
        side = (side or "").lower()
        if side not in ("buy", "sell"):
            return {"ok": False, "message": "side must be buy|sell"}
        try:
            amt_quote = float(amount)
        except Exception:
            return {"ok": False, "message": "amount must be number"}
        if amt_quote <= 0:
            return {"ok": False, "message": "amount > 0 required"}
        if int(getattr(self.cfg, "ENABLE_TRADING", 1)) != 1:
            return {"ok": False, "message": "trading disabled"}

        symbol = getattr(self.cfg, "SYMBOL", "BTC/USDT")

        if riskmod is not None:
            ok, reason = riskmod.validate_open(self.cfg, self.exchange, symbol)
            if not ok:
                return {"ok": False, "message": f"blocked: {reason}"}

        last_price = None
        try:
            if hasattr(self.exchange, "fetch_ticker"):
                t = self.exchange.fetch_ticker(symbol) or {}
                last_price = float(t.get("last") or t.get("close") or 0)
        except Exception:
            last_price = None
        if not last_price or last_price <= 0:
            return {"ok": False, "message": "price unavailable"}

        qty = self._quote_to_base(amt_quote, last_price)

        if self.position and ((side == "sell" and self.position.get("side") == "buy") or (side == "buy" and self.position.get("side") == "sell")):
            self._close_position(last_price, "TG close (opposite side)")
            return {"ok": True, "message": f"close via opposite side @ {last_price:.2f}"}

        ok = self._create_market_order(symbol, side, qty, last_price, order_type="tg")
        if not ok:
            return {"ok": False, "message": "order rejected by adapter"}

        sl, tp = self._compute_sl_tp(last_price, 0.0, side)
        self.position = {
            "symbol": symbol, "side": side, "qty": qty, "entry_price": last_price,
            "opened_at": datetime.now(timezone.utc).isoformat(), "sl": sl, "tp": tp,
            "trailing_max": last_price if side == "buy" else None, "status": "open",
        }
        if int(self.cfg.PAPER_MODE) == 1:
            open_list = self.paper.load_positions(); open_list.append(self.position); self.paper.save_positions(open_list)

        return {"ok": True, "message": f"{side} {qty:.8f} @ {last_price:.2f}"}

    def request_close_position(self, *, source: str = "telegram") -> dict:
        symbol = getattr(self.cfg, "SYMBOL", "BTC/USDT")
        last_price = None
        try:
            if hasattr(self.exchange, "fetch_ticker"):
                t = self.exchange.fetch_ticker(symbol) or {}
                last_price = float(t.get("last") or t.get("close") or 0)
        except Exception:
            last_price = None
        if not last_price or last_price <= 0:
            return {"ok": False, "message": "price unavailable"}

        if not self.position and int(getattr(self.cfg, "PAPER_MODE", 1)) == 1:
            open_list = self.paper.load_positions()
            if open_list:
                self.position = open_list[-1]

        if not self.position:
            return {"ok": False, "message": "no position"}

        self._close_position(last_price, "TG close")
        return {"ok": True, "message": f"closed @ {last_price:.2f}"}

    def _notify(self, text: str):
        try:
            if self.notifier: self.notifier(text)
        except Exception:
            logger.debug("notifier failed", exc_info=True)

def get_bot(exchange: Any, notifier=None, settings: Optional[Settings] = None) -> TradingBot:
    return TradingBot.get_instance(exchange=exchange, notifier=notifier, settings=settings)



