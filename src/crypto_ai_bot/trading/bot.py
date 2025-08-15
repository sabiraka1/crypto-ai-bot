# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# Единые настройки
from crypto_ai_bot.core.settings import Settings

# Клиент биржи (обёртка над ccxt)
from crypto_ai_bot.trading.exchange_client import ExchangeClient

# Единый пайплайн сигналов
try:
    from crypto_ai_bot.core.signals.aggregator import aggregate_features
    from crypto_ai_bot.core.signals.validator import validate_features
    from crypto_ai_bot.core.signals.policy import decide as policy_decide
except Exception:  # совместимость, если core/ ещё не полностью внедрён
    from crypto_ai_bot.trading.signals.sinyal_skorlayici import aggregate_features  # type: ignore
    from crypto_ai_bot.trading.signals.signal_validator import validate_features  # type: ignore
    from crypto_ai_bot.trading.signals.entry_policy import decide as policy_decide  # type: ignore

log = logging.getLogger(__name__)


# -------------------------------
# Надёжное файловое хранилище Paper-режима
# -------------------------------

@dataclass
class PaperFiles:
    positions: Path
    orders: Path
    pnl: Path


class PaperStore:
    """
    Хранит paper-позиции/ордера/PNL в CSV/JSON.
    Создаёт каталоги и файлы при инициализации.
    """
    def __init__(self, cfg: Settings) -> None:
        base_dir = Path(cfg.DATA_DIR or "data")
        base_dir.mkdir(parents=True, exist_ok=True)

        self.files = PaperFiles(
            positions=base_dir.joinpath(cfg.PAPER_POSITIONS_FILE or "paper_positions.json"),
            orders=base_dir.joinpath(cfg.PAPER_ORDERS_FILE or "paper_orders.csv"),
            pnl=base_dir.joinpath(cfg.PAPER_PNL_FILE or "paper_pnl.csv"),
        )
        self._ensure_files()

    def _ensure_files(self) -> None:
        # positions.json
        if not self.files.positions.exists():
            self.files.positions.parent.mkdir(parents=True, exist_ok=True)
            self.files.positions.write_text("{}", encoding="utf-8")

        # orders.csv
        if not self.files.orders.exists():
            self.files.orders.parent.mkdir(parents=True, exist_ok=True)
            self.files.orders.write_text(
                "ts,side,price,amount,order_id,comment\n", encoding="utf-8"
            )

        # pnl.csv
        if not self.files.pnl.exists():
            self.files.pnl.parent.mkdir(parents=True, exist_ok=True)
            self.files.pnl.write_text("ts,pnl\n", encoding="utf-8")

    # ---- примитивные операции (можно расширить позже) ----
    def load_positions(self) -> Dict[str, Any]:
        try:
            return json.loads(self.files.positions.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_positions(self, positions: Dict[str, Any]) -> None:
        self.files.positions.write_text(json.dumps(positions, ensure_ascii=False), encoding="utf-8")

    def append_order(self, ts: int, side: str, price: float, amount: float, order_id: str, comment: str = "") -> None:
        line = f"{ts},{side},{price},{amount},{order_id},{comment}\n"
        with self.files.orders.open("a", encoding="utf-8") as f:
            f.write(line)

    def append_pnl(self, ts: int, pnl: float) -> None:
        line = f"{ts},{pnl}\n"
        with self.files.pnl.open("a", encoding="utf-8") as f:
            f.write(line)


# -------------------------------
# Торговый бот (singleton)
# -------------------------------

class TradingBot:
    """
    Компактный единый движок.
    - Не плодит глобальные синглтоны;
    - Имеет необязательную фоновую петлю (ensure_loop_thread/start).
    """

    _singleton: Optional["TradingBot"] = None

    def __init__(self, exchange: ExchangeClient, notifier, settings: Settings) -> None:
        self.cfg = settings
        self.exchange = exchange
        self.notifier = notifier

        # Директории проекта
        for d in (self.cfg.DATA_DIR, self.cfg.LOGS_DIR, self.cfg.MODEL_DIR):
            if d:
                Path(d).mkdir(parents=True, exist_ok=True)

        # Paper-хранилище (используем даже в LIVE для логов/статистики)
        self.paper = PaperStore(self.cfg)

        # Поток фоновой петли
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_running = False

        log.info("TradingBot initialized (symbol=%s, tf=%s, paper=%s, trading=%s)",
                 self.cfg.SYMBOL, self.cfg.TIMEFRAME, bool(self.cfg.PAPER_MODE), bool(self.cfg.ENABLE_TRADING))

    # ------------ Singleton API ------------

    @classmethod
    def get_instance(cls, exchange: ExchangeClient, notifier, settings: Settings) -> "TradingBot":
        if cls._singleton is None:
            cls._singleton = TradingBot(exchange, notifier, settings)
        return cls._singleton

    # ------------ Управление фоновым циклом ------------

    def start(self) -> None:
        """Совместимость: имя, которое ожидал сервер."""
        self.ensure_loop_thread()

    def ensure_loop_thread(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive():
            return
        self._loop_running = True
        self._loop_thread = threading.Thread(target=self._loop, name="TradingLoop", daemon=True)
        self._loop_thread.start()
        log.info("Trading loop thread started")

    def stop(self) -> None:
        self._loop_running = False

    # ------------ Основная логика ------------

    def _loop(self) -> None:
        interval_sec = self._resolve_interval_sec(self.cfg.ANALYSIS_INTERVAL)
        while self._loop_running:
            t0 = time.time()
            try:
                self.tick()
            except Exception as e:
                log.exception("tick() failed: %s", e)
            # Пауза до следующего цикла
            elapsed = time.time() - t0
            sleep_for = max(5.0, interval_sec - elapsed)
            time.sleep(sleep_for)

    def _resolve_interval_sec(self, v_any: Any) -> float:
        """
        ANALYSIS_INTERVAL может быть:
        - числом в секундах (int/float/str);
        - строкой вида '15' (сек) или '15m' (минуты).
        """
        if v_any is None:
            return 60.0
        s = str(v_any).strip().lower()
        try:
            if s.endswith("m"):
                return float(int(s[:-1]) * 60)
            return float(s)
        except Exception:
            return 60.0

    def tick(self) -> None:
        """
        Один шаг анализа/решения.
        В текущей безопасной версии — только собираем фичи и выносим решение, без выставления реальных ордеров.
        """
        cfg = self.cfg

        # 1) Сбор фичей
        try:
            features = aggregate_features(cfg=cfg, exchange=self.exchange)
        except Exception as e:
            log.warning("aggregate_features error: %s", e)
            return

        # 2) Валидация
        try:
            ok, reasons = validate_features(features, cfg=cfg)
            if not ok:
                log.debug("validation failed: %s", "; ".join(reasons or []))
                return
        except Exception as e:
            log.warning("validate_features error: %s", e)
            return

        # 3) Решение (entry/hold/exit)
        try:
            decision = policy_decide(features, cfg=cfg)
        except Exception as e:
            log.warning("policy.decide error: %s", e)
            return

        # 4) Действие (упрощённо/безопасно)
        # Здесь можно подключить PositionManager и RiskManager.
        # Для надёжного старта ограничимся уведомлением.
        try:
            pretty = json.dumps(decision, ensure_ascii=False)
            self.notifier(f"📊 Decision: {pretty}")
        except Exception:
            pass

        log.debug("tick done")

# -------------------------------
# Фабрика единственного экземпляра
# -------------------------------

def get_bot(exchange: ExchangeClient, notifier, settings: Optional[Settings] = None) -> TradingBot:
    cfg = settings or Settings.build()
    return TradingBot.get_instance(exchange=exchange, notifier=notifier, settings=cfg)
