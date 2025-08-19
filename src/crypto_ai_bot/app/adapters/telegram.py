# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations
import json
from typing import Any, Dict, List
from fastapi.responses import JSONResponse

from crypto_ai_bot.core.brokers.symbols import normalize_symbol
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.signals._fusion import explain as explain_signals


def _help_text() -> str:
    return (
        "Команды:\n"
        "/start      — приветствие\n"
        "/help       — краткая справка и список команд\n"
        "/status     — текущее состояние (режим, символ, таймфрейм, профиль, health)\n"
        "/test       — тестовый ответ (smoke)\n"
        "/profit     — PnL% и кумулятив по закрытым сделкам\n"
        "/positions  — открытые позиции (опц.: /positions BTCUSDT)\n"
        "/eval [SYMBOL] [TF] [LIMIT] — разовая оценка без торговли\n"
        "/why [SYMBOL] [TF] [LIMIT]  — объяснение последнего решения\n"
    )

def _make_reply(chat_id: int | None, text: str) -> JSONResponse:
    if chat_id is None:
        return JSONResponse({"ok": True})
    payload = {"method": "sendMessage", "chat_id": chat_id, "text": text}
    return JSONResponse(payload)

def _fmt_positions(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "Нет открытых позиций."
    lines = []
    for r in rows:
        sym = r.get("symbol", "?")
        qty = float(r.get("qty", 0.0))
        avg = r.get("avg_price", None)
        if avg is None:
            lines.append(f"• {sym}: qty={qty}")
        else:
            lines.append(f"• {sym}: qty={qty}, avg={float(avg):.6f}")
    return "\n".join(lines)


async def handle_update(app, body: bytes, container: Any):
    try:
        update = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "bad-json"}, status_code=400)

    msg = (update.get("message") or {}) if isinstance(update, dict) else {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")

    if not text:
        return _make_reply(chat_id, "Пришлите команду. /help")

    if text.startswith("/start"):
        return _make_reply(chat_id, "Привет! Я бот торговой системы. Наберите /help.")

    if text.startswith("/help"):
        return _make_reply(chat_id, _help_text())

    if text.startswith("/test"):
        return _make_reply(chat_id, "✅ OK (smoke). Бот отвечает и подключён к приложению.")

    if text.startswith("/positions"):
        try:
            parts = text.split(None, 1)
            default_sym = getattr(container.settings, "SYMBOL", "BTC/USDT")
            sym = parts[1].strip() if len(parts) > 1 else default_sym
            sym = normalize_symbol(sym)

            rows = container.positions_repo.get_open()
            if sym:
                rows = [r for r in rows if str(r.get("symbol")) == sym]

            msg_text = _fmt_positions(rows) if rows else f"{sym}: нет открытых позиций"
            return _make_reply(chat_id, msg_text)
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    if text.startswith("/status"):
        try:
            mode = getattr(container.settings, "MODE", "paper")
            symbol = getattr(container.settings, "SYMBOL", "BTC/USDT")
            timeframe = getattr(container.settings, "TIMEFRAME", "1h")
            profile = getattr(container.settings, "PROFILE", getattr(container.settings, "ENV", "default"))
            bus_h = container.bus.health() if hasattr(container.bus, "health") else {"running": True, "dlq_size": None}
            pending = container.trades_repo.count_pending()
            lines = [
                f"mode: {mode}",
                f"symbol: {symbol}",
                f"timeframe: {timeframe}",
                f"profile: {profile}",
                f"bus: running={bus_h.get('running')}, dlq={bus_h.get('dlq_size')}, p99={bus_h.get('p99_ms')}ms",
                f"pending orders: {pending}",
            ]
            return _make_reply(chat_id, "\n".join(lines))
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    if text.startswith("/profit"):
        try:
            parts = text.split(None, 1)
            default_sym = getattr(container.settings, "SYMBOL", "BTC/USDT")
            sym = parts[1].strip() if len(parts) > 1 else default_sym
            sym = normalize_symbol(sym)

            summary = container.trades_repo.realized_pnl_summary(symbol=sym)
            wl = f"{int(summary['wins'])}/{int(summary['losses'])}"
            resp = (
                f"{sym}\n"
                f"Closed trades: {int(summary['closed_trades'])} (W/L {wl})\n"
                f"PnL: {float(summary['pnl_abs']):.6f} USDT\n"
                f"PnL%: {float(summary['pnl_pct']):.4f}%"
            )
            return _make_reply(chat_id, resp)
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    if text.startswith("/eval"):
        # /eval [SYMBOL] [TF] [LIMIT]   (TF/LIMIT пока опциональны; TF может использоваться внутри build)
        try:
            parts = text.split()
            default_sym = getattr(container.settings, "SYMBOL", "BTC/USDT")
            sym = normalize_symbol(parts[1]) if len(parts) > 1 else normalize_symbol(default_sym)
            out = evaluate(cfg=container.settings, broker=container.broker, positions_repo=container.positions_repo, symbol=sym, external=None, bus=container.bus)
            d = out.get("decision", {})
            return _make_reply(chat_id, f"{sym}\nDecision: {d.get('action')} | score={float(d.get('score', 0.0)):.4f} | reason={d.get('reason')}")
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    if text.startswith("/why"):
        # /why [SYMBOL] [TF] [LIMIT]
        try:
            parts = text.split()
            default_sym = getattr(container.settings, "SYMBOL", "BTC/USDT")
            sym = normalize_symbol(parts[1]) if len(parts) > 1 else normalize_symbol(default_sym)
            out = evaluate(cfg=container.settings, broker=container.broker, positions_repo=container.positions_repo, symbol=sym, external=None, bus=None)
            features = out.get("features") or {}
            ctx = out.get("context") or {}
            exp = explain_signals(features, ctx)
            top = list(exp["contributions"].items())[:6]
            lines = [f"{sym}", "Top signals:"]
            lines += [f"• {k}: {v:+.4f}" for k, v in top]
            lines.append(f"Score: {sum(exp['contributions'].values()):+.4f} | buy≥{exp['thresholds']['buy']} sell≤{exp['thresholds']['sell']}")
            return _make_reply(chat_id, "\n".join(lines))
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    return _make_reply(chat_id, "Неизвестная команда. /help")
