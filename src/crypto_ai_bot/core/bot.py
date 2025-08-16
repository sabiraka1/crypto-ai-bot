from __future__ import annotations

from typing import Any, Dict, Optional
from decimal import Decimal

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.brokers.base import create_broker
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe

from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute


class _ReposFacade:
    """
    Простая фабрика репозиториев, совместимая с ожиданиями use-cases:
      repos.idempotency(tx), repos.trades(tx), repos.positions(tx), repos.audit(tx)
    Параметр tx не используется — репозитории работают поверх общего соединения.
    """

    def __init__(self, con, cfg: Settings) -> None:
        self._con = con
        self._cfg = cfg

    def idempotency(self, tx):
        return SqliteIdempotencyRepository(self._con)

    def trades(self, tx):
        return SqliteTradeRepository(self._con)

    def positions(self, tx):
        return SqlitePositionRepository(self._con)

    def audit(self, tx):
        return SqliteAuditRepository(self._con)


class Bot:
    """Тонкая фасада над use-cases. Создаёт брокера через фабрику.
    Совместима с telegram-адаптером (ожидает broker, uow, repos).
    """

    def __init__(
        self,
        cfg: Settings,
        con=None,
        broker=None,
    ) -> None:
        self.cfg = cfg
        self.con = con or connect(cfg.DB_PATH)
        self.broker = broker or create_broker(cfg)

        # UoW + фабрика репозиториев (ожидаются telegram-адаптером)
        self.uow = SqliteUnitOfWork(self.con)
        self.repos = _ReposFacade(self.con, cfg)

        # Минимальные одиночные репозитории — оставляем для совместимости и тестов
        self.trades_repo = SqliteTradeRepository(self.con)
        self.positions_repo = SqlitePositionRepository(self.con)
        self.audit_repo = SqliteAuditRepository(self.con)

    def evaluate(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        sym = normalize_symbol(symbol or self.cfg.SYMBOL)
        tf = normalize_timeframe(timeframe or self.cfg.TIMEFRAME)
        lookback = int(limit or getattr(self.cfg, "LOOKBACK_LIMIT", 300))
        return uc_evaluate(self.cfg, self.broker, symbol=sym, timeframe=tf, limit=lookback)

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        # Новый контракт: use_cases.place_order(cfg, broker, uow, repos, decision)
        return uc_place_order(self.cfg, self.broker, self.uow, self.repos, decision)

    def eval_and_execute(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        sym = normalize_symbol(symbol or self.cfg.SYMBOL)
        tf = normalize_timeframe(timeframe or self.cfg.TIMEFRAME)
        lookback = int(limit or getattr(self.cfg, "LOOKBACK_LIMIT", 300))
        repos = {
            "positions": self.positions_repo,
            "trades": self.trades_repo,
            "audit": self.audit_repo,
        }
        return uc_eval_and_execute(self.cfg, self.broker, repos, symbol=sym, timeframe=tf, limit=lookback)

    def get_status(self) -> Dict[str, Any]:
        mode = "paper" if getattr(self.cfg, "PAPER_MODE", True) else "live"
        return {
            "mode": mode,
            "symbol": self.cfg.SYMBOL,
            "timeframe": self.cfg.TIMEFRAME,
        }
