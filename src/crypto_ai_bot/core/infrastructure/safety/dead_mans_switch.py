from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.decimal import dec

# Тематик события: берём из EVT, иначе — строковый дефолт
try:
    from crypto_ai_bot.core.application import events_topics as EVT  # type: ignore
    _DMS_TOPIC = getattr(EVT, "DMS_TRIGGERED", "safety.dead_mans_switch.triggered")
except Exception:
    _DMS_TOPIC = "safety.dead_mans_switch.triggered"

# Брокерные типы (OrderSide для SELL)
try:
    from crypto_ai_bot.core.application.ports import BrokerPort, OrderSide, PositionDTO  # type: ignore
except Exception:  # минимальные заглушки для стат. анализа/редких сценариев импорта
    BrokerPort = Any  # type: ignore[assignment]
    OrderSide = type("OrderSide", (), {"SELL": "sell"})  # type: ignore[assignment]
    PositionDTO = Any  # type: ignore[assignment]

_log = get_logger("safety.dms")


@dataclass
class DeadMansSwitch:
    """
    Dead Man's Switch: если цена упала относительно последней "здоровой" цены
    более чем на max_impact_pct, закрываем позицию маркетом и шлём событие.
    """
    storage: Any | None = None    # ожидается storage.get_position(symbol) или storage.positions[symbol]
    broker: BrokerPort | None = None
    symbol: str | None = None
    timeout_ms: int = 120_000     # используется внешним шедулером; внутри не нужен
    rechecks: int = 1             # сколько раз перепроверять цену с задержкой
    recheck_delay_sec: float = 0.0
    max_impact_pct: Decimal = Decimal("3")  # порог просадки в %
    bus: Any | None = None

    _last_healthy_price: Decimal | None = None

    # -------- helpers --------

    async def _current_price(self) -> Decimal:
        """
        Безопасно извлекаем last/bid/ask из TickerDTO-подобного объекта или Mapping.
        """
        assert self.broker and self.symbol
        t = await self.broker.fetch_ticker(self.symbol)

        # Сначала пробуем как объект с атрибутами
        for attr in ("last", "bid", "ask"):
            v = getattr(t, attr, None)
            if v is not None:
                return dec(str(v))

        # Затем как Mapping (dict-подобный)
        if isinstance(t, Mapping):
            for k in ("last", "bid", "ask"):
                v = t.get(k)
                if v is not None:
                    return dec(str(v))

        return dec("0")

    def _get_position(self) -> Optional[PositionDTO | Any]:
        """
        Унифицированный доступ к позиции из storage:
        - storage.get_position(symbol)
        - storage.positions.get(symbol)
        """
        if not self.storage or not self.symbol:
            return None

        # 1) метод хранилища
        if hasattr(self.storage, "get_position"):
            try:
                pos = self.storage.get_position(self.symbol)  # type: ignore[no-any-return]
                if pos:
                    return pos
            except Exception:
                _log.error("dms_storage_get_position_failed", extra={"symbol": self.symbol}, exc_info=True)

        # 2) словарь positions
        try:
            positions = getattr(self.storage, "positions", None)
            if positions is not None and hasattr(positions, "get"):
                return positions.get(self.symbol)
        except Exception:
            _log.error("dms_positions_dict_failed", extra={"symbol": self.symbol}, exc_info=True)

        return None

    @staticmethod
    def _position_base_qty(pos: PositionDTO | Any) -> Decimal:
        """
        Унифицированно достаём размер позиции (base quantity).
        Поддерживаем частые варианты полей.
        """
        for name in ("amount", "size", "qty", "quantity", "base_qty"):
            if hasattr(pos, name):
                try:
                    return dec(str(getattr(pos, name)))
                except Exception:
                    pass
        return dec("0")

    # -------- core --------

    async def check(self) -> None:
        """
        Основная проверка:
        - читаем текущую цену (с перепроверками),
        - сравниваем с порогом относительно _last_healthy_price,
        - если пробитие — пытаемся закрыть базу целиком и публикуем событие.
        """
        if not self.broker or not self.symbol:
            return

        last = await self._current_price()
        if self._last_healthy_price is None:
            # Первая «здоровая» цена — текущая
            self._last_healthy_price = last
            return

        # Перепроверки цены (если заданы)
        cur = last
        for _ in range(max(0, int(self.rechecks))):
            if self.recheck_delay_sec:
                await asyncio.sleep(self.recheck_delay_sec)
            cur = await self._current_price()

        # Порог "просадки" от последней здоровой цены
        # threshold = (1 - max_impact_pct/100) * last_healthy
        threshold = (dec("100") - self.max_impact_pct) / dec("100") * self._last_healthy_price

        if cur < threshold:
            # Берём открытый размер позиции
            pos = self._get_position()
            qty = self._position_base_qty(pos) if pos else dec("0")

            if qty > dec("0"):
                try:
                    # Продаём маркетом базовую валюту в полном объёме
                    await self.broker.create_market_order(
                        self.symbol, OrderSide.SELL, qty, client_order_id="dms_auto_exit"
                    )
                    _log.warning("dms_market_sell", extra={"symbol": self.symbol, "qty": str(qty)})
                except Exception as exc:
                    _log.warning("dms_sell_failed", extra={"symbol": self.symbol, "error": str(exc)}, exc_info=True)

            # Публикуем событие
            if self.bus and hasattr(self.bus, "publish"):
                try:
                    await self.bus.publish(
                        _DMS_TOPIC,
                        {
                            "symbol": self.symbol,
                            "prev": str(self._last_healthy_price),
                            "last": str(cur),
                            "qty": str(qty),
                        },
                    )
                except Exception:
                    _log.error("dms_publish_failed", extra={"symbol": self.symbol}, exc_info=True)

            # После срабатывания сдвигаем «здоровую» цену к текущей
            self._last_healthy_price = cur
        else:
            # Апдейт «здоровой» цены до max(prev, cur) — trailing
            self._last_healthy_price = max(self._last_healthy_price, cur)
