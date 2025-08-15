# src/crypto_ai_bot/utils/envtools.py
import os
from typing import Set, Tuple

def webhook_secret_candidates() -> Set[str]:
    """
    РЎРїРёСЃРѕРє РґРѕРїСѓСЃС‚РёРјС‹С… СЃРµРєСЂРµС‚РѕРІ РІРµР±С…СѓРєР° (РµСЃР»Рё Р·Р°РґР°РЅС‹ РѕР±Р° вЂ” РїСЂРёРЅРёРјР°РµРј Р»СЋР±РѕР№).
    РќРµ РјРµРЅСЏРµС‚ РїРѕРІРµРґРµРЅРёРµ, С‚РѕР»СЊРєРѕ СѓР±РёСЂР°РµС‚ СЂР°СЃСЃРёРЅС…СЂРѕРЅ РјРµР¶РґСѓ WEBHOOK_SECRET Рё TELEGRAM_SECRET_TOKEN.
    """
    s1 = (os.getenv("WEBHOOK_SECRET") or "").strip()
    s2 = (os.getenv("TELEGRAM_SECRET_TOKEN") or "").strip()
    return {s for s in (s1, s2) if s}

def webhook_secret_for_set() -> str:
    """
    РљР°РєРѕР№ СЃРµРєСЂРµС‚ РїРµСЂРµРґР°РІР°С‚СЊ РІ setWebhook.
    РџСЂРµРґРїРѕС‡РёС‚Р°РµРј WEBHOOK_SECRET, РёРЅР°С‡Рµ TELEGRAM_SECRET_TOKEN, РёРЅР°С‡Рµ "".
    """
    for name in ("WEBHOOK_SECRET", "TELEGRAM_SECRET_TOKEN"):
        v = (os.getenv(name) or "").strip()
        if v:
            return v
    return ""

def exchange_keys() -> Tuple[str, str]:
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ (api_key, api_secret), С‡РёС‚Р°СЏ Р»РёР±Рѕ API_KEY/API_SECRET, Р»РёР±Рѕ GATE_API_KEY/GATE_API_SECRET.
    РЈ РІР°СЃ СѓР¶Рµ РёРґРµРЅС‚РёС‡РЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ вЂ” СЌС‚Рѕ РїСЂРѕСЃС‚Рѕ РµРґРёРЅР°СЏ С‚РѕС‡РєР° С‡С‚РµРЅРёСЏ.
    """
    key = (os.getenv("API_KEY") or os.getenv("GATE_API_KEY") or "").strip()
    sec = (os.getenv("API_SECRET") or os.getenv("GATE_API_SECRET") or "").strip()
    return key, sec








