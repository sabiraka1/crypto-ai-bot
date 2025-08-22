from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Dict, Optional, Any

from ..storage.facade import Storage
from ..events.bus import AsyncEventBus
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.metrics import timer, inc


@dataclass
class ExitsConfig:
    """
    Конфигурация защитных выходов:
    - sl_pct: размер стоп-лосса в долях (0.01 = 1%)
    - tp_pct: размер тейк-профита в долях (0.02 = 2%); 0 = без TP
    Значения по умолчанию безопасные и не требуют ENV.
    """
    sl_pct: Decimal = Decimal("0.01")
    tp_pct: Decimal = Decimal("0.02")


@dataclass
class ExitsPlan:
    """
    План защитных выходов, рассчитанный от цены входа.
    Хранится in-memory (идемпотентно формируется при наличии позиции).
    """
    symbol: str
    entry_price: Decimal
    sl_price: Decimal
    tp_price: Optional[Decimal]  # может быть None, если tp_pct == 0
    ts_ms: int


class ProtectiveExits:
    """
    ProtectiveExits 1.1

    ▶ Назначение:
      - Идемпотентно держит актуальный план SL/TP для каждой пары с позицией.
      - НЕ размещает стоп/лимит заявки у биржи (для этого в IBroker нет методов);
        оркестратор/стратегия могут использовать план, чтобы принимать решения,
        а sell выполняется через обычный рыночный путь create_market_sell_base.

    ▶ Совместимость:
      - Сигнатуры не менялись; bus опционален.
      - Не требует ENV. При желании значения можно пробросить из Settings через compose.

    ▶ Метрики:
      - exits_ensure_ms — латентность ensure()
      - exits_set_total — план создан/обновлён
      - exits_already_ok_total — план уже актуален
      - exits_cleared_total — план очищён (позиция закрыта)
      - exits_skip_no_entry_total — нет входной цены — план не сформирован
    """

    def __init__(
        self,
        *,
        storage: Storage,
        bus: Optional[AsyncEventBus] = None,
        config: Optional[ExitsConfig] = None,
    ) -> None:
        self._log = get_logger("risk.exits")
        self._storage = storage
        self._bus = bus
        self._cfg = config or ExitsConfig()
        # in-memory планы по символам
        self._plans: Dict[str, ExitsPlan] = {}

    # ---------- публичное API ----------

    def current_plan(self, symbol: str) -> Optional[ExitsPlan]:
        """Возвращает текущий план (если есть)."""
        return self._plans.get(symbol)

    async def ensure(self, *, symbol: str) -> Optional[ExitsPlan]:
        """
        Идемпотентно гарантирует, что для текущей открытой позиции есть план SL/TP.
        - Если позиции нет → план очищается, если был.
        - Если позиция есть → рассчитываем/обновляем план от входной цены.
        """
        with timer("exits_ensure_ms", {"symbol": symbol}, unit="ms"):
            pos = self._safe_get_position(symbol)

            # 1) Нет позиции → очищаем план, если он был
            if not pos or not self._positive(pos.get("base_qty", 0)):
                if symbol in self._plans:
                    self._plans.pop(symbol, None)
                    inc("exits_cleared_total", {"symbol": symbol})
                    self._log.info("exits_cleared", extra={"symbol": symbol})
                return None

            # 2) Определяем входную цену
            entry_price = self._detect_entry_price(symbol, pos)
            if entry_price is None or entry_price <= 0:
                # Без входной цены план не формируем — избежим ложных SL/TP
                inc("exits_skip_no_entry_total", {"symbol": symbol})
                self._log.info("exits_skip_no_entry", extra={"symbol": symbol, "pos": pos})
                return None

            # 3) Рассчитываем SL/TP
            plan = self._build_plan(symbol, entry_price)

            # 4) Идемпотентность: если новый план равен старому — ничего не делаем
            old = self._plans.get(symbol)
            if old and self._equal_plans(old, plan):
                inc("exits_already_ok_total", {"symbol": symbol})
                return old

            # 5) Обновляем план и публикуем событие
            self._plans[symbol] = plan
            inc("exits_set_total", {"symbol": symbol})
            self._log.info("exits_updated", extra={"symbol": symbol, "plan": asdict(plan)})

            if self._bus:
                try:
                    await self._bus.publish(
                        topic="protective_exit.updated",
                        payload={"symbol": symbol, "plan": asdict(plan)},
                        key=symbol,
                    )
                except Exception as exc:
                    self._log.error("publish_failed", extra={"symbol": symbol, "error": str(exc)})

            return plan

    # ---------- утилиты / внутренняя логика ----------

    def _build_plan(self, symbol: str, entry_price: Decimal) -> ExitsPlan:
        sl = (entry_price * (Decimal("1.0") - self._cfg.sl_pct)).quantize(Decimal("0.00000001"))
        tp: Optional[Decimal] = None
        if self._cfg.tp_pct and self._cfg.tp_pct > 0:
            tp = (entry_price * (Decimal("1.0") + self._cfg.tp_pct)).quantize(Decimal("0.00000001"))
        return ExitsPlan(
            symbol=symbol,
            entry_price=entry_price,
            sl_price=sl,
            tp_price=tp,
            ts_ms=now_ms(),
        )

    @staticmethod
    def _equal_plans(a: ExitsPlan, b: ExitsPlan) -> bool:
        # Сравнение с учётом округления
        return (
            a.symbol == b.symbol
            and a.entry_price == b.entry_price
            and a.sl_price == b.sl_price
            and (a.tp_price or Decimal("0")) == (b.tp_price or Decimal("0"))
        )

    def _detect_entry_price(self, symbol: str, pos: Dict[str, Any]) -> Optional[Decimal]:
        """
        Пытаемся определить «цену входа» из известных полей позиции.
        Поддерживаем несколько возможных вариантов названий, чтобы не быть хрупкими.
        Если ничего нет — возвращаем None (ensure() корректно обработает).
        """
        # Наиболее вероятные имена в разных реализациях:
        candidates = [
            "avg_entry_price",
            "avg_price",
            "entry_price",
            "avg_quote_per_base",
            "price",
        ]
        for name in candidates:
            v = pos.get(name)
            if self._positive(v):
                try:
                    return Decimal(str(v))
                except Exception:
                    pass

        # Попытка вычислить (если доступны cost/base_qty)
        cost = pos.get("cost_quote")
        base = pos.get("base_qty")
        if self._positive(cost) and self._positive(base):
            try:
                return (Decimal(str(cost)) / Decimal(str(base)))
            except Exception:
                return None
        return None

    def _safe_get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получает позицию из storage и приводит к dict с минимальным набором ключей:
        { base_qty: Decimal/float, ...возможные поля со средней ценой... }
        """
        try:
            p = self._storage.positions.get_position(symbol)
        except Exception:
            return None
        if p is None:
            return None
        # поддерживаем dataclass/obj/dict
        if isinstance(p, dict):
            return p
        d: Dict[str, Any] = {}
        for attr in ("base_qty", "avg_entry_price", "avg_price", "entry_price", "avg_quote_per_base", "price", "cost_quote"):
            if hasattr(p, attr):
                d[attr] = getattr(p, attr)
        # часто есть геттер get_base_qty(...)
        if "base_qty" not in d:
            try:
                d["base_qty"] = self._storage.positions.get_base_qty(symbol)
            except Exception:
                pass
        return d

    @staticmethod
    def _positive(x: Any) -> bool:
        try:
            return x is not None and float(x) > 0
        except Exception:
            return False
