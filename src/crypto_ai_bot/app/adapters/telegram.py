# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations
import json
from typing import Any, Dict, List, Tuple
from fastapi.responses import JSONResponse


# ---------- helpers: formatting ----------

def _help_text() -> str:
    return (
        "Команды:\n"
        "/start  — приветствие\n"
        "/help   — краткая справка и список команд\n"
        "/status — текущее состояние (режим, символ, таймфрейм, профиль, health)\n"
        "/test   — тестовый ответ (smoke)\n"
        "/profit — PnL%% и кумулятив по закрытым сделкам\n"
        "/positions — открытые позиции\n"
    )

def _make_reply(chat_id: int | None, text: str) -> JSONResponse:
    # Telegram webhook reply: можно сразу вернуть JSON c методом
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
        qty = r.get("qty", 0.0)
        avg = r.get("avg_price", None)
        if avg is None:
            lines.append(f"• {sym}: qty={qty}")
        else:
            lines.append(f"• {sym}: qty={qty}, avg={round(float(avg), 6)}")
    return "\n".join(lines)


# ---------- helpers: PnL over filled trades ----------

def _load_filled_trades(con, symbol: str | None = None) -> List[Tuple[int, str, str, float, float, float]]:
    """
    Возвращает список сделок (ts, symbol, side, price, qty, fee_amt) только state='filled'.
    Порядок — по времени возрастанию.
    """
    if symbol:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' AND symbol=? ORDER BY ts ASC",
            (symbol,)
        )
    else:
        cur = con.execute(
            "SELECT ts, symbol, side, price, qty, COALESCE(fee_amt,0.0) "
            "FROM trades WHERE state='filled' ORDER BY ts ASC"
        )
    return [(int(ts), str(sym), str(side), float(price), float(qty), float(fee))
            for (ts, sym, side, price, qty, fee) in cur.fetchall()]

def _realized_pnl_summary(con, symbol: str | None = None) -> Dict[str, Any]:
    """
    Простой учёт по average-cost:
      - Покупки увеличивают объём и усредняют цену.
      - Продажи уменьшают объём и формируют realized PnL: (sell_px - avg_cost) * sell_qty - fee_sell.
    Возвращает: {'closed_trades', 'wins', 'losses', 'pnl_abs', 'pnl_pct'}.
    pnl_pct считается от суммарной стоимости проданных лотов (cost basis), чтобы не зависеть от незакрытых позиций.
    """
    rows = _load_filled_trades(con, symbol)
    if not rows:
        return {"closed_trades": 0, "wins": 0, "losses": 0, "pnl_abs": 0.0, "pnl_pct": 0.0}

    # состояние по символам
    inv: Dict[str, Dict[str, float]] = {}  # {symbol: {'qty': q, 'avg': avg}}
    realized = 0.0
    realized_cost = 0.0
    wins = losses = closed = 0

    for _, sym, side, px, qty, fee in rows:
        s = inv.setdefault(sym, {"qty": 0.0, "avg": 0.0})
        if side == "buy":
            new_qty = s["qty"] + qty
            if new_qty <= 0:
                s["qty"] = 0.0
                s["avg"] = 0.0
            else:
                s["avg"] = (s["avg"] * s["qty"] + px * qty) / new_qty if s["qty"] > 0 else px
                s["qty"] = new_qty
        else:  # sell
            sell_qty = min(qty, s["qty"]) if s["qty"] > 0 else qty
            pnl = (px - s["avg"]) * sell_qty - fee
            realized += pnl
            realized_cost += s["avg"] * sell_qty
            closed += 1
            if pnl >= 0:
                wins += 1
            else:
                losses += 1
            s["qty"] = max(0.0, s["qty"] - sell_qty)
            if s["qty"] == 0.0:
                s["avg"] = 0.0

    pnl_pct = (realized / realized_cost * 100.0) if realized_cost > 0 else 0.0
    return {
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "pnl_abs": realized,
        "pnl_pct": pnl_pct,
    }


# ---------- main handler ----------

async def handle_update(app, body: bytes, container: Any):
    """
    Сигнатура, которую вызывает server.py.
    """
    # 1) Парсим апдейт
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

    # 2) Роутинг команд
    if text.startswith("/start"):
        return _make_reply(chat_id, "Привет! Я бот торговой системы. Наберите /help.")

    if text.startswith("/help"):
        return _make_reply(chat_id, _help_text())

    if text.startswith("/test"):
        return _make_reply(chat_id, "✅ OK (smoke). Бот отвечает и подключён к приложению.")

    if text.startswith("/positions"):
        try:
            rows = container.positions_repo.get_open()
            return _make_reply(chat_id, _fmt_positions(rows))
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
                f"bus: running={bus_h.get('running')}, dlq={bus_h.get('dlq_size')}",
                f"pending orders: {pending}",
            ]
            return _make_reply(chat_id, "\n".join(lines))
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    if text.startswith("/profit"):
        try:
            # по умолчанию — по всем символам; если нужно по конкретному:
            # можно поддержать "/profit BTC/USDT"
            parts = text.split(None, 1)
            sym = parts[1].strip() if len(parts) > 1 else None
            summary = _realized_pnl_summary(container.con, sym)
            pct = round(summary["pnl_pct"], 4)
            abs_usd = round(summary["pnl_abs"], 6)
            wl = f"{summary['wins']}/{summary['losses']}"
            resp = (
                f"Closed trades: {summary['closed_trades']} (W/L {wl})\n"
                f"PnL: {abs_usd} USDT\n"
                f"PnL%: {pct}%"
            )
            return _make_reply(chat_id, resp)
        except Exception as e:
            return _make_reply(chat_id, f"Ошибка: {e!r}")

    # 3) Дефолт
    return _make_reply(chat_id, "Неизвестная команда. /help")
