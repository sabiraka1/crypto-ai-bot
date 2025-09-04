from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from crypto_ai_bot.app.adapters.telegram import TelegramAlerts
from crypto_ai_bot.core.application import events_topics as events_topics  # noqa: N812
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc

_log = get_logger("subscribers.telegram")


# --- Localization ---
def _t(lang: str, key: str, **kw: str) -> str:
    L = {
        "en": {
            "orch_paused": "Auto trading has been *paused* for {symbol}. Reason: {reason}",
            "orch_resumed": "Auto trading has been *resumed* for {symbol}.",
            "trade_ok": "✅ Trade completed for {symbol}: {side} {quote} {quote_ccy}",
            "trade_fail": "❌ Trade failed for {symbol}. Reason: {reason}",
            "risk_blocked": "⛔ Trade blocked by risk rule: {rule}",
            "budget_exceeded": "⛔ Budget exceeded. Daily PnL: {pnl} {ccy}",
            "broker_error": "⚠️ Broker error: {msg}",
            "health": "❤️ Health: price={price} spread={spread} spread%={spread_pct}",
            "dms_triggered": "🛑 DMS TRIGGERED for {symbol}. Prev={prev}, Last={last}",
            "dms_skipped": "ℹ️ DMS skipped for {symbol}. Prev={prev}, Last={last}",
            "alerts_forwarded": "📣 Alert forwarded: {labels}",
        },
        "tr": {
            "orch_paused": "{symbol} için otomatik işlem *durduruldu*. Neden: {reason}",
            "orch_resumed": "{symbol} için otomatik işlem *devam ediyor*.",
            "trade_ok": "✅ İşlem tamamlandı {symbol}: {side} {quote} {quote_ccy}",
            "trade_fail": "❌ İşlem başarısız {symbol}. Neden: {reason}",
            "risk_blocked": "⛔ Risk kuralı engelledi: {rule}",
            "budget_exceeded": "⛔ Bütçe aşıldı. Günlük PnL: {pnl} {ccy}",
            "broker_error": "⚠️ Broker hatası: {msg}",
            "health": "❤️ Sağlık: fiyat={price} spread={spread} spread%={spread_pct}",
            "dms_triggered": "🛑 DMS TETİKLENDİ {symbol}. Önceki={prev}, Son={last}",
            "dms_skipped": "ℹ️ DMS atlandı {symbol}. Önceki={prev}, Son={last}",
            "alerts_forwarded": "📣 İleti yönlendirildi: {labels}",
        },
        "ru": {
            "orch_paused": "Автоторговля *приостановлена* для {symbol}. Причина: {reason}",
            "orch_resumed": "Автоторговля *возобновлена* для {symbol}.",
            "trade_ok": "✅ Сделка завершена {symbol}: {side} {quote} {quote_ccy}",
            "trade_fail": "❌ Сделка не выполнена для {symbol}. Причина: {reason}",
            "risk_blocked": "⛔ Сделка заблокирована правилом риска: {rule}",
            "budget_exceeded": "⛔ Бюджет превышен. Дневной PnL: {pnl} {ccy}",
            "broker_error": "⚠️ Ошибка брокера: {msg}",
            "health": "❤️ Состояние: цена={price} спрэд={spread} спрэд%={spread_pct}",
            "dms_triggered": "🛑 DMS СРАБОТАЛ для {symbol}. Было={prev}, Стало={last}",
            "dms_skipped": "ℹ️ DMS пропущен для {symbol}. Было={prev}, Стало={last}",
            "alerts_forwarded": "📣 Оповещение переслано: {labels}",
        },
    }
    lang = (lang or "en").lower()
    if lang not in L:
        lang = "en"
    tpl = L[lang].get(key, L["en"].get(key, key))
    return tpl.format(**kw)


# noqa: C901


def attach_alerts(bus: Any, settings: Any) -> None:
    """
    Подписки на события шины и форвардинг в Telegram.
    """
    tg = TelegramAlerts(settings=settings)

    def _lang() -> str:
        try:
            return str(getattr(settings, "LANG", "en")).lower()
        except Exception:
            return "en"

    # --- Helpers to send messages ---

    async def _send_text(text: str) -> None:
        try:
            await tg.send_text(text)
            inc("telegram.send_text.ok")
        except Exception:
            inc("telegram.send_text.err")
            _log.exception("telegram_send_text_failed")

    async def _send_alert(text: str, labels: dict[str, str] | None = None) -> None:
        try:
            await tg.send_text(text)
            if labels:
                await tg.send_text(f"Labels: {labels}")
            inc("telegram.alert.ok")
        except Exception:
            inc("telegram.alert.err")
            _log.exception("telegram_alert_failed")

    # ----------------------------- Event handlers -----------------------------

    async def _on_orch_paused(payload: dict[str, Any]) -> None:
        text = _t(_lang(), "orch_paused", symbol=payload.get("symbol", "?"), reason=payload.get("reason", "n/a"))
        await _send_text(text)

    async def _on_orch_resumed(payload: dict[str, Any]) -> None:
        text = _t(_lang(), "orch_resumed", symbol=payload.get("symbol", "?"))
        await _send_text(text)

    async def _on_trade_completed(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "trade_ok",
            symbol=payload.get("symbol", "?"),
            side=payload.get("side", "?"),
            quote=str(payload.get("quote", "0")),
            quote_ccy=payload.get("quote_ccy", ""),
        )
        await _send_text(text)

    async def _on_trade_failed(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "trade_fail",
            symbol=payload.get("symbol", "?"),
            reason=payload.get("reason", "unknown"),
        )
        await _send_text(text)

    async def _on_risk_blocked(payload: dict[str, Any]) -> None:
        text = _t(_lang(), "risk_blocked", rule=payload.get("rule", "unknown"))
        await _send_text(text)

    async def _on_budget_exceeded(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "budget_exceeded",
            pnl=str(payload.get("pnl", "0")),
            ccy=payload.get("ccy", ""),
        )
        await _send_text(text)

    async def _on_broker_error(payload: dict[str, Any]) -> None:
        text = _t(_lang(), "broker_error", msg=payload.get("message", "unknown"))
        await _send_text(text)

    async def _on_health(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "health",
            price=str(payload.get("price", "?")),
            spread=str(payload.get("spread", "?")),
            spread_pct=str(payload.get("spread_pct", "?")),
        )
        await _send_text(text)

    async def _on_dms_triggered(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "dms_triggered",
            symbol=payload.get("symbol", "?"),
            prev=str(payload.get("prev", "?")),
            last=str(payload.get("last", "?")),
        )
        await _send_text(text)

    async def _on_dms_skipped(payload: dict[str, Any]) -> None:
        text = _t(
            _lang(),
            "dms_skipped",
            symbol=payload.get("symbol", "?"),
            prev=str(payload.get("prev", "?")),
            last=str(payload.get("last", "?")),
        )
        await _send_text(text)

    async def _on_alertmanager(payload: dict[str, Any]) -> None:
        labels = payload.get("labels", {})
        await _send_alert(_t(_lang(), "alerts_forwarded", labels=str(labels)), labels=labels)

    # ----------------------------- Subscriptions -----------------------------

    bus.on(events_topics.ORCH_AUTO_PAUSED, _on_orch_paused)
    bus.on(events_topics.ORCH_AUTO_RESUMED, _on_orch_resumed)

    bus.on(events_topics.TRADE_COMPLETED, _on_trade_completed)
    bus.on(events_topics.TRADE_FAILED, _on_trade_failed)
    bus.on(events_topics.RISK_BLOCKED, _on_risk_blocked)
    bus.on(events_topics.BUDGET_EXCEEDED, _on_budget_exceeded)

    bus.on(events_topics.BROKER_ERROR, _on_broker_error)
    bus.on(events_topics.HEALTH_REPORT, _on_health)

    bus.on(events_topics.DMS_TRIGGERED, _on_dms_triggered)
    bus.on(events_topics.DMS_SKIPPED, _on_dms_skipped)

    bus.on(events_topics.ALERTS_ALERTMANAGER, _on_alertmanager)
