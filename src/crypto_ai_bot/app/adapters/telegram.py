from __future__ import annotations

from typing import Any, Dict, Optional, List
from decimal import Decimal, InvalidOperation

from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe


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
        "Команды:\n"
        "/start — приветствие\n"
        "/status — режим/символ/экспозиция/PNL/последний score\n"
        "/why — показать последний Decision (explain)\n"
        "/eval <SYMBOL> <TF> [LIMIT] — оценка без сделки\n"
        "/buy <AMOUNT> — рыночная покупка (режим зависит от MODE)\n"
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


def _sum_exposure(opens: List[Dict[str, Any]]) -> str:
    total = Decimal("0")
    for p in opens or []:
        try:
            sz = p.get("size")
            total += Decimal(str(sz))
        except (InvalidOperation, TypeError):
            continue
    return format(total.copy_abs(), "f")


def _format_explain(row: Dict[str, Any]) -> str:
    d = row.get("decision") or {}
    e = row.get("explain") or {}
    score = d.get("score")
    action = d.get("action")
    parts: List[str] = [f"Последний Decision: action={action}, score={score}"]

    signals = e.get("signals") or {}
    if signals:
        shown = []
        for k, v in list(signals.items())[:8]:
            shown.append(f"{k}={v}")
        parts.append("signals: " + ", ".join(shown))

    weights = e.get("weights") or {}
    if weights:
        parts.append("weights: " + ", ".join(f"{k}={v}" for k, v in weights.items()))

    blocks = e.get("blocks") or {}
    blocked = [k for k, ok in blocks.items() if ok is False]
    if blocked:
        parts.append("blocked_by: " + ", ".join(blocked))

    ctx = e.get("context") or {}
    if ctx:
        show_ctx = []
        for k in ("price", "atr", "atr_pct", "regime"):
            if k in ctx:
                show_ctx.append(f"{k}={ctx[k]}")
        if show_ctx:
            parts.append("context: " + ", ".join(show_ctx))

    return "\n".join(parts)


async def handle_update(update: Dict[str, Any], cfg, bot, http=None, repos=None) -> Dict[str, Any]:
    """
    Тонкий маршрутизатор Telegram → бизнес-логика.
    Зависимости: cfg, bot(evaluate/execute/get_status), http(optional), repos(optional).
    """
    http = http or get_http_client()
    text = _message_text(update)
    chat_id = _chat_id(update)
    if chat_id is None:
        return {"ok": True}

    if not text or text == "/start":
        metrics.inc("tg_command_total", {"cmd": "start"})
        return _reply(chat_id, "Привет! Я crypto-ai-bot.\n" + _help_text())

    if text.startswith("/help"):
        metrics.inc("tg_command_total", {"cmd": "help"})
        return _reply(chat_id, _help_text())

    if text.startswith("/status"):
        metrics.inc("tg_command_total", {"cmd": "status"})
        mode = getattr(cfg, "MODE", "unknown")
        sym = normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT"))
        tf = normalize_timeframe(getattr(cfg, "TIMEFRAME", "1h"))

        pos_cnt, exposure = 0, "0"
        if repos and getattr(repos, "positions", None):
            try:
                opens = repos.positions.get_open() or []
                pos_cnt = len(opens)
                exposure = _sum_exposure(opens)
            except Exception:
                pass

        pnl = None
        # Если подключили трекер — возьмём PnL
        if repos and getattr(repos, "tracker", None):
            try:
                val = repos.tracker.get_pnl()
                pnl = str(val)
            except Exception:
                pnl = None

        last_score = None
        if repos and getattr(repos, "decisions", None):
            try:
                rows = repos.decisions.list_recent(limit=1) or []
                if rows:
                    last_score = (rows[0].get("decision") or {}).get("score")
            except Exception:
                pass

        lines = [
            f"MODE={mode}",
            f"SYMBOL={sym}",
            f"TF={tf}",
            f"open_positions={pos_cnt}",
            f"exposure={exposure}",
        ]
        if pnl is not None:
            lines.append(f"pnl={pnl}")
        if last_score is not None:
            lines.append(f"last_score={last_score}")

        return _reply(chat_id, "\n".join(lines))

    if text.startswith("/why"):
        metrics.inc("tg_command_total", {"cmd": "why"})
        if not repos or not getattr(repos, "decisions", None):
            return _reply(chat_id, "Хранилище решений недоступно.")
        try:
            rows = repos.decisions.list_recent(limit=1) or []
            if not rows:
                return _reply(chat_id, "Пока нет сохранённых решений.")
            return _reply(chat_id, _format_explain(rows[0]))
        except Exception as e:
            return _reply(chat_id, f"/why ошибка: {type(e).__name__}: {e}")

    if text.startswith("/eval"):
        metrics.inc("tg_command_total", {"cmd": "eval"})
        try:
            args = _parse_eval_args(text, cfg)
            decision = bot.evaluate(**args)
            return _reply(chat_id, f"evaluate({args['symbol']},{args['timeframe']},{args['limit']}) → {decision}")
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
        try:
            args = {
                "symbol": normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT")),
                "timeframe": normalize_timeframe(getattr(cfg, "TIMEFRAME", "1h")),
                "limit": int(getattr(cfg, "LIMIT", 300)),
            }
            decision = bot.evaluate(**args)
            d = decision if isinstance(decision, dict) else dict(decision)
            d["action"] = "buy"
            d["size"] = str(amount)
            res = bot.execute(d)
            return _reply(chat_id, f"Заявка отправлена: {res}")
        except Exception as e:
            return _reply(chat_id, f"/buy ошибка: {type(e).__name__}: {e}")

    metrics.inc("tg_command_total", {"cmd": "unknown"})
    return _reply(chat_id, "Неизвестная команда.\n" + _help_text())
