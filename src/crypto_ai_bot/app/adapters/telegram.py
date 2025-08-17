from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, Optional


# =============== Public surface ===============
# handle_update — единственная публичная функция.
# Никакой бизнес-логики/доступа к БД/брокеру тут нет — только маршрутизация команд и форматирование текста.
#
# Зависимости передаются "снаружи" как коллбеки:
#   - tick_call(symbol, timeframe, limit) -> dict  (внутри сервер вызывает use_case eval_and_execute)
#   - why_last_call(symbol, timeframe) -> dict|None (внутри сервер берёт из repos.decisions)
#
# Это сохраняет нам правило: app/* не лезет в core/* напрямую.


@dataclass
class TgDeps:
    tick_call: Callable[[str, str, int], Dict[str, Any]]
    why_last_call: Callable[[str, str], Optional[Dict[str, Any]]]
    default_symbol: str
    default_timeframe: str
    default_limit: int = 300


def handle_update(update: Dict[str, Any], deps: TgDeps) -> Dict[str, Any]:
    """
    Возвращает словарь с полями:
      {
        "chat_id": int,
        "text": str,
        "parse_mode": "Markdown" | "HTML" | None
      }
    Сервер сам отправит это в Telegram API (через utils.http_client).
    """
    chat_id = _extract_chat_id(update)
    if chat_id is None:
        return {"chat_id": 0, "text": "unsupported update", "parse_mode": None}

    text = _extract_text(update) or ""
    cmd, args = _parse_command(text)

    if cmd in ("/start", "/help"):
        return {"chat_id": chat_id, "text": _help_text(deps), "parse_mode": "Markdown"}

    if cmd == "/status":
        return {
            "chat_id": chat_id,
            "text": _status_text(deps),
            "parse_mode": "Markdown",
        }

    if cmd == "/tick":
        sym, tf, lim = _parse_symbol_tf_limit(args, deps)
        res = deps.tick_call(sym, tf, lim)
        return {"chat_id": chat_id, "text": _format_tick_result(sym, tf, res), "parse_mode": "Markdown"}

    if cmd == "/why":
        sym, tf, _ = _parse_symbol_tf_limit(args, deps)
        row = deps.why_last_call(sym, tf)
        if not row:
            return {"chat_id": chat_id, "text": f"Нет сохранённых решений для *{sym}* [{tf}].", "parse_mode": "Markdown"}
        return {"chat_id": chat_id, "text": _format_why_last(sym, tf, row), "parse_mode": "Markdown"}

    # неизвестная команда → help
    return {"chat_id": chat_id, "text": _help_text(deps), "parse_mode": "Markdown"}


# =============== helpers ===============

def _extract_chat_id(update: Dict[str, Any]) -> Optional[int]:
    try:
        return int(update["message"]["chat"]["id"])
    except Exception:
        try:
            return int(update["callback_query"]["message"]["chat"]["id"])
        except Exception:
            return None


def _extract_text(update: Dict[str, Any]) -> Optional[str]:
    try:
        return str(update["message"]["text"])
    except Exception:
        try:
            return str(update["callback_query"]["data"])
        except Exception:
            return None


def _parse_command(text: str) -> tuple[str, list[str]]:
    text = (text or "").strip()
    if not text.startswith("/"):
        return "/help", []
    parts = text.split()
    cmd = parts[0].split("@", 1)[0].lower()
    return cmd, parts[1:]


def _parse_symbol_tf_limit(args: list[str], deps: TgDeps) -> tuple[str, str, int]:
    sym = deps.default_symbol
    tf = deps.default_timeframe
    lim = deps.default_limit
    if len(args) >= 1:
        sym = args[0].upper()
    if len(args) >= 2:
        tf = args[1]
    if len(args) >= 3:
        try:
            lim = max(50, min(2000, int(args[2])))
        except Exception:
            pass
    return sym, tf, lim


def _help_text(deps: TgDeps) -> str:
    return (
        "*Crypto AI Bot*\n\n"
        "Доступные команды:\n"
        "• `/status` — текущие настройки (symbol/timeframe)\n"
        "• `/tick [SYMBOL] [TF] [LIMIT]` — выполнить один цикл оценки/исполнения\n"
        "• `/why [SYMBOL] [TF]` — показать последнее сохранённое решение и объяснение\n\n"
        f"_По умолчанию_: `{deps.default_symbol}` [{deps.default_timeframe}], LIMIT={deps.default_limit}\n"
    )


def _status_text(deps: TgDeps) -> str:
    return (
        "*Статус*\n"
        f"Symbol: `{deps.default_symbol}`\n"
        f"Timeframe: `{deps.default_timeframe}`\n"
        f"Limit: `{deps.default_limit}`\n"
    )


def _format_tick_result(sym: str, tf: str, res: Dict[str, Any]) -> str:
    try:
        d = res.get("decision") or {}
        action = str(d.get("action") or "hold")
        size = _as_str(d.get("size", "0"))
        score = d.get("score")
        lines = [f"*Tick* `{sym}` [{tf}] → **{action}** {size}"]
        if score is not None:
            lines.append(f"score = `{score:.3f}`")
        # краткое объяснение, если есть
        explain = d.get("explain") or {}
        sigs = explain.get("signals") or {}
        if sigs:
            short = ", ".join(f"{k}={_short_num(v)}" for k, v in list(sigs.items())[:5])
            lines.append(f"_signals_: {short}")
        return "\n".join(lines)
    except Exception:
        return f"*Tick* `{sym}` [{tf}] → результат: `{res}`"


def _format_why_last(sym: str, tf: str, row: Dict[str, Any]) -> str:
    action = str(row.get("action") or "hold")
    size = row.get("size") or "0"
    score = row.get("score")
    lines = [f"*Последнее решение* `{sym}` [{tf}] → **{action}** {size}"]
    if score is not None:
        lines.append(f"score = `{score:.3f}`" if isinstance(score, float) else f"score = `{score}`")

    explain = row.get("explain") or {}
    if isinstance(explain, dict):
        sigs = explain.get("signals") or {}
        blocks = explain.get("blocks") or {}
        if sigs:
            lines.append("_signals_: " + ", ".join(f"{k}={_short_num(v)}" for k, v in list(sigs.items())[:6]))
        if blocks:
            # покажем кратко, что блокировало/влияла
            shown = []
            for k, v in blocks.items():
                if isinstance(v, (int, float, str, bool)):
                    shown.append(f"{k}={v}")
                if len(shown) >= 6:
                    break
            if shown:
                lines.append("_blocks_: " + ", ".join(shown))

    return "\n".join(lines)


def _as_str(val: Any) -> str:
    if isinstance(val, Decimal):
        return format(val, "f")
    return str(val)


def _short_num(v: Any) -> str:
    try:
        f = float(v)
        return f"{f:.3f}"
    except Exception:
        return str(v)
