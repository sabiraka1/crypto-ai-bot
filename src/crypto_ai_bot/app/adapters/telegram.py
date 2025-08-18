# src/crypto_ai_bot/app/adapters/telegram.py
from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics

# мягкая зависимость, чтобы не падать
try:
    from crypto_ai_bot.core.use_cases.evaluate import evaluate
except Exception:
    evaluate = None  # type: ignore


def _text(update: Dict[str, Any]) -> str:
    return str((((update or {}).get("message") or {}).get("text")) or "").strip()


def _reply(text: str) -> Dict[str, Any]:
    # server.py вернёт этот JSON как webhook-ответ
    return {"ok": True, "text": text}


def _base_url(cfg: Any) -> Optional[str]:
    # Если захочешь, добавь в Settings BASE_URL, чтобы в телеге были кликабельные ссылки.
    return getattr(cfg, "BASE_URL", None) or None


def handle_update(
    update: Dict[str, Any],
    cfg: Any,
    broker: Any,
    http: Any,
    *,
    bus: Any | None = None,
    repos: Any | None = None,
) -> Dict[str, Any]:
    """
    Поддерживаем команды:
      /start — приветствие
      /help — список команд
      /status — текущая позиция (улучшено)
      /eval — оценка решения
      /why — объяснение
      /test — «пробный» сигнал + ссылка на график цены
      /profit — кривая доходности + ссылка на график
    """
    txt = _text(update).lower()
    base = _base_url(cfg)
    sym = getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = getattr(cfg, "TIMEFRAME", "1h")
    limit = int(getattr(cfg, "LIMIT_BARS", 300) or 300)

    if txt.startswith("/start"):
        return _reply("Привет! Доступно: /help")

    if txt.startswith("/help"):
        return _reply(
            "Команды:\n"
            "/status — позиция и режим\n"
            "/eval — оценка решения\n"
            "/why — объяснение решения\n"
            "/test — тестовый график и сигнал\n"
            "/profit — кривая доходности"
        )

    if txt.startswith("/status"):
        # улучшенный статус: режим + краткая позиция
        mode = getattr(cfg, "MODE", "paper")
        pos_line = "позиции недоступны"
        if repos is not None and getattr(repos, "positions", None) is not None:
            try:
                opens = repos.positions.get_open() or []
                if not opens:
                    pos_line = "открытых позиций нет"
                else:
                    # возьмём первую (или соберём краткую сводку)
                    parts = []
                    for p in opens[:5]:
                        try:
                            parts.append(f"{p.get('symbol')} qty={p.get('qty')} avg={p.get('avg_price')}")
                        except Exception:
                            continue
                    more = "" if len(opens) <= 5 else f" (+{len(opens)-5} ещё)"
                    pos_line = "; ".join(parts) + more
            except Exception:
                pos_line = "не удалось получить позиции"
        return _reply(f"MODE={mode}; SYMBOL={sym}; TF={tf}\n{pos_line}")

    if txt.startswith("/eval"):
        if evaluate is None:
            return _reply("Оценка недоступна.")
        try:
            d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            act = str(d.get("action", "hold"))
            sc = d.get("score_blended") or d.get("score") or d.get("score_base")
            return _reply(f"Decision: {act} (score={sc})")
        except Exception as e:
            return _reply(f"Ошибка eval: {type(e).__name__}: {e}")

    if txt.startswith("/why"):
        if evaluate is None:
            return _reply("Объяснение недоступно.")
        try:
            d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            exp = d.get("explain", {})
            return _reply(f"Explain: {exp}")
        except Exception as e:
            return _reply(f"Ошибка explain: {type(e).__name__}: {e}")

    if txt.startswith("/test"):
        # решение + ссылка на график
        link = (f"{base}/chart/test?symbol={sym}&timeframe={tf}&limit={limit}") if base else f"/chart/test?symbol={sym}&timeframe={tf}&limit={limit}"
        if evaluate is None:
            return _reply(f"График: {link}\nОценка недоступна.")
        try:
            d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=limit)
            act = str(d.get("action", "hold"))
            sc = d.get("score_blended") or d.get("score") or d.get("score_base")
            return _reply(f"Decision: {act} (score={sc})\nГрафик: {link}")
        except Exception as e:
            return _reply(f"График: {link}\nОшибка eval: {type(e).__name__}: {e}")

    if txt.startswith("/profit"):
        link = (f"{base}/chart/profit?symbol={sym}") if base else f"/chart/profit?symbol={sym}"
        # попутно посчитаем краткую сводку
        summary = "нет данных"
        if repos is not None and getattr(repos, "trades", None) is not None:
            try:
                # используем доступный API last_closed_pnls(N) если есть
                series = []
                if hasattr(repos.trades, "last_closed_pnls"):
                    series = list(repos.trades.last_closed_pnls(100))  # type: ignore
                if series:
                    total = sum(float(x) for x in series if x is not None)
                    summary = f"ΣPnL={total:.4f} (последние {len(series)} сделок)"
            except Exception:
                summary = "не удалось получить PnL"
        return _reply(f"{summary}\nГрафик: {link}")

    metrics.inc("telegram_unknown_cmd_total")
    return _reply("Неизвестная команда. /help — список команд")
