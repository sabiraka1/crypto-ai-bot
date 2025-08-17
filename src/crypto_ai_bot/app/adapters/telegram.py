# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

from typing import Any, Dict, Optional, List
from decimal import Decimal

from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

# Ожидаем, что снаружи нам дадут:
#   cfg: Settings
#   bot: core.bot.Bot (имеет evaluate()/execute()/get_status())
#   repos: объект с .decisions/.positions/.trades (может быть None в раннем режиме)


def _message_text(update: Dict[str, Any]) -> str:
    msg = (update or {}).get("message") or {}
    return (msg.get("text") or "").strip()


def _chat_id(update: Dict[str, Any]) -> Optional[int]:
    msg = (update or {}).get("message") or {}
    chat = msg.get("chat") or {}
    return chat.get("id")


def _reply(chat_id: int, text: str) -> Dict[str, Any]:
    return {"method": "sendMessage", "chat_id": chat_id, "text": text}


def _help_text() -> str:
    return (
        "Доступные команды:\n"
        "/start — приветствие\n"
        "/status — статус бота/режим/здоровье\n"
        "/why — последний Decision с explain()\n"
        "/eval <SYMBOL> <TF> [LIMIT] — только оценка (без ордера)\n"
        "/buy <AMOUNT> — рыночная покупка (paper/live зависит от MODE)\n"
    )


def _parse_eval_args(text: str, cfg) -> Dict[str, Any]:
    # /eval BTC/USDT 1h 300
    parts = text.split()
    symbol = normalize_symbol(parts[1] if len(parts) > 1 else getattr(cfg, "SYMBOL", "BTC/USDT"))
    timeframe = normalize_timeframe(parts[2] if len(parts) > 2 else getattr(cfg, "TIMEFRAME", "1h"))
    try:
        limit = int(parts[3]) if len(parts) > 3 else int(getattr(cfg, "LIMIT", 300))
    except Exception:
        limit = int(getattr(cfg, "LIMIT", 300))
    return {"symbol": symbol, "timeframe": timeframe, "limit": limit}


async def handle_update(update: Dict[str, Any], cfg, bot, http=None, repos=None) -> Dict[str, Any]:
    """
    Тонкий маршрутизатор команд Telegram → вызовы бизнес-логики.
    Никакой прямой работы с индикаторами/репозиториями/брокером — всё через bot/use-cases.
    """
    http = http or get_http_client()
    text = _message_text(update)
    chat_id = _chat_id(update)
    if chat_id is None:
        return {"ok": True}  # нет получателя — молча

    if not text or text == "/start":
        metrics.inc("tg_command_total", {"cmd": "start"})
        return _reply(chat_id, "Привет! Я crypto-ai-bot. " + _help_text())

    if text.startswith("/help"):
        metrics.inc("tg_command_total", {"cmd": "help"})
        return _reply(chat_id, _help_text())

    if text.startswith("/status"):
        metrics.inc("tg_command_total", {"cmd": "status"})
        # простая сводка: режим/символ/таймфрейм и открытые позиции (если есть репо)
        mode = getattr(cfg, "MODE", "unknown")
        sym = getattr(cfg, "SYMBOL", "BTC/USDT")
        tf = getattr(cfg, "TIMEFRAME", "1h")
        pos_cnt = 0
        try:
            if repos and getattr(repos, "positions", None):
                opens = repos.positions.get_open() or []
                pos_cnt = len(opens)
        except Exception:
            pos_cnt = -1
        return _reply(chat_id, f"Статус: MODE={mode}, SYMBOL={sym}, TF={tf}, открытых позиций: {pos_cnt}")

    if text.startswith("/why"):
        metrics.inc("tg_command_total", {"cmd": "why"})
        # берём последний Decision из репозитория решений (если подключен)
        if not repos or not getattr(repos, "decisions", None):
            return _reply(chat_id, "Хранилище решений недоступно.")
        try:
            rows = repos.decisions.list_recent(limit=1) or []
            if not rows:
                return _reply(chat_id, "Пока нет сохранённых решений.")
            row = rows[0]
            # ожидаемый формат: {"decision": {...}, "explain": {...}, ...}
            expl = row.get("explain") or {}
            # делаем краткую выжимку
            signals = expl.get("signals") or {}
            blocks = expl.get("blocks") or {}
            score = (row.get("decision") or {}).get("score")
            parts = [f"Последний Decision: score={score}"]
            if signals:
                top = ", ".join(f"{k}={v}" for k, v in list(signals.items())[:6])
                parts.append(f"signals: {top}")
            if blocks:
                denied = [k for k, v in blocks.items() if not v]
                if denied:
                    parts.append(f"blocked_by: {', '.join(denied)}")
            return _reply(chat_id, "\n".join(parts))
        except Exception as e:
            return _reply(chat_id, f"/why ошибка: {type(e).__name__}: {e}")

    if text.startswith("/eval"):
        metrics.inc("tg_command_total", {"cmd": "eval"})
        try:
            args = _parse_eval_args(text, cfg)
            decision = bot.evaluate(**args)
            return _reply(chat_id, f"evaluate({args['symbol']}, {args['timeframe']}, {args['limit']}) → {decision}")
        except Exception as e:
            return _reply(chat_id, f"/eval ошибка: {type(e).__name__}: {e}")

    if text.startswith("/buy"):
        metrics.inc("tg_command_total", {"cmd": "buy"})
        parts = text.split()
        if len(parts) < 2:
            return _reply(chat_id, "Формат: /buy <AMOUNT>")
        try:
            amount = Decimal(parts[1])
        except Exception:
            return _reply(chat_id, "AMOUNT должен быть числом, напр. 0.01")

        # демонстрационный вызов: используем evaluate → execute (как eval_and_execute внутри бота)
        try:
            args = {"symbol": normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT")),
                    "timeframe": normalize_timeframe(getattr(cfg, "TIMEFRAME", "1h")),
                    "limit": int(getattr(cfg, "LIMIT", 300))}
            decision = bot.evaluate(**args)
            decision_dict = decision if isinstance(decision, dict) else dict(decision)  # на всякий случай
            decision_dict["action"] = "buy"
            decision_dict["size"] = str(amount)
            res = bot.execute(decision_dict)  # дальше use-case place_order решит по Settings/SafeMode/Paper
            return _reply(chat_id, f"Заявка отправлена: {res}")
        except Exception as e:
            return _reply(chat_id, f"/buy ошибка: {type(e).__name__}: {e}")

    # неизвестная команда
    metrics.inc("tg_command_total", {"cmd": "unknown"})
    return _reply(chat_id, "Неизвестная команда. " + _help_text())
