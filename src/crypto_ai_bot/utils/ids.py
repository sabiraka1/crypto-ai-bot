from __future__ import annotations

import secrets
import time


def make_client_order_id(exchange_id: str, tag: str) -> str:
    """ДћвЂДћВµДћВ·ДћВѕДћВїДћВ°Г‘ВЃДћВЅГ‘вЂ№ДћВ№ clientOrderId: Г‘вЂљДћВѕДћВ»Г‘Е’ДћВєДћВѕ [a-zA-Z0-9_-]."""
    ms = int(time.time() * 1000)
    rnd = secrets.token_hex(4)
    safe_tag = "".join(ch if ch.isalnum() else "-" for ch in tag)[:32]
    safe_ex = "".join(ch if ch.isalnum() else "-" for ch in exchange_id)[:16]
    return f"{safe_ex}-{safe_tag}-{ms}-{rnd}"


def sanitize_ascii(value: str) -> str:
    """ДћВ¤ДћВёДћВ»Г‘Е’Г‘вЂљГ‘в‚¬Г‘Ж’ДћВµГ‘вЂљ Г‘ВЃГ‘вЂљГ‘в‚¬ДћВѕДћВєГ‘Ж’, ДћВѕГ‘ВЃГ‘вЂљДћВ°ДћВІДћВ»Г‘ВЏГ‘ВЏ Г‘вЂљДћВѕДћВ»Г‘Е’ДћВєДћВѕ ДћВ±ДћВµДћВ·ДћВѕДћВїДћВ°Г‘ВЃДћВЅГ‘вЂ№ДћВµ ASCII Г‘ВЃДћВёДћВјДћВІДћВѕДћВ»Г‘вЂ№ [a-z0-9-]."""
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value if ch.isalnum() or ch in "-_")
