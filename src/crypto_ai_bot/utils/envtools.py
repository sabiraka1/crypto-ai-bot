# src/crypto_ai_bot/utils/envtools.py
import os
from typing import Set, Tuple

def webhook_secret_candidates() -> Set[str]:
    """
    Список допустимых секретов вебхука (если заданы оба — принимаем любой).
    Не меняет поведение, только убирает рассинхрон между WEBHOOK_SECRET и TELEGRAM_SECRET_TOKEN.
    """
    s1 = (os.getenv("WEBHOOK_SECRET") or "").strip()
    s2 = (os.getenv("TELEGRAM_SECRET_TOKEN") or "").strip()
    return {s for s in (s1, s2) if s}

def webhook_secret_for_set() -> str:
    """
    Какой секрет передавать в setWebhook.
    Предпочитаем WEBHOOK_SECRET, иначе TELEGRAM_SECRET_TOKEN, иначе "".
    """
    for name in ("WEBHOOK_SECRET", "TELEGRAM_SECRET_TOKEN"):
        v = (os.getenv(name) or "").strip()
        if v:
            return v
    return ""

def exchange_keys() -> Tuple[str, str]:
    """
    Возвращает (api_key, api_secret), читая либо API_KEY/API_SECRET, либо GATE_API_KEY/GATE_API_SECRET.
    У вас уже идентичные значения — это просто единая точка чтения.
    """
    key = (os.getenv("API_KEY") or os.getenv("GATE_API_KEY") or "").strip()
    sec = (os.getenv("API_SECRET") or os.getenv("GATE_API_SECRET") or "").strip()
    return key, sec
