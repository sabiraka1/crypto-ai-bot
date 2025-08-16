from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

from crypto_ai_bot.core.use_cases.evaluate import evaluate as uc_evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order as uc_place_order
from crypto_ai_bot.utils import charts
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
# Нормализация символов/таймфреймов: единый реестр
from crypto_ai_bot.core.brokers import normalize_symbol, normalize_timeframe

log = get_logger(__name__)


def _parse_symbol_timeframe(
    raw_symbol: str | None,
    raw_timeframe: str | None,
    cfg,
) -> Tuple[str, str]:
    """
    Единая нормализация пользовательского ввода.
    Если параметр не передан — берём дефолт из Settings.
    """
    symbol = normalize_symbol(raw_symbol or cfg.SYMBOL)
    timeframe = normalize_timeframe(raw_timeframe or cfg.TIMEFRAME)
    return symbol, timeframe


async def handle_update(update: Dict[str, Any], cfg, bot, http) -> Dict[str, Any]:
    """
    Тонкий адаптер: парсим команду → дергаем use-cases → форматируем ответ.
    Никакой бизнес-логики здесь нет.
    """
    try:
        text = (update.get("message", {}) or {}).get("text") or ""
        parts = text.strip().split()
        cmd = (parts[0] if parts else "").lower()

        if cmd in ("/start", "/help"):
            inc("tg_command_total", {"cmd": "help"})
            return {"text": "Привет! Команды: /status, /why, /buy <size>, /sell <size>."}

        if cmd == "/status":
            inc("tg_command_total", {"cmd": "status"})
            symbol, timeframe = _parse_symbol_timeframe(None, None, cfg)
            d = uc_evaluate(cfg, bot.broker, symbol=symbol, timeframe=timeframe, limit=cfg.DECISION_LIMIT)
            return {"text": f"Status {symbol} {timeframe}: {d['action']} score={d.get('score'):.3f}"}

        if cmd == "/why":
            inc("tg_command_total", {"cmd": "why"})
            symbol, timeframe = _parse_symbol_timeframe(None, None, cfg)
            d = uc_evaluate(cfg, bot.broker, symbol=symbol, timeframe=timeframe, limit=cfg.DECISION_LIMIT)
            return {"text": f"Explain: {d.get('explain', {})}"}

        if cmd in ("/buy", "/sell"):
            side = "buy" if cmd == "/buy" else "sell"
            inc("tg_command_total", {"cmd": side})
            size = Decimal(parts[1]) if len(parts) > 1 else Decimal("0")
            symbol, timeframe = _parse_symbol_timeframe(None, None, cfg)

            decision = {
                "action": side,
                "size": size,
                "sl": None,
                "tp": None,
                "trail": None,
                "score": 1.0,
                "explain": {"source": "telegram_manual"},
            }
            res = uc_place_order(cfg, bot.broker, bot.uow, bot.repos, decision)
            return {"text": f"Order: {res}"}

        # неизвестная команда
        inc("tg_command_total", {"cmd": "unknown"})
        return {"text": "Неизвестная команда. /help"}

    except Exception as exc:  # noqa: BLE001
        log.exception("telegram_adapter_failed", extra={"error": str(exc)})
        return {"text": f"Ошибка: {exc}"}
