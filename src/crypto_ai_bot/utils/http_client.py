# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройки по умолчанию (можно переопределить аргументами функций)
_DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
_DEFAULT_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
_DEFAULT_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.3"))  # секунды

# Один общий сессионный клиент с ретраями
_session: Optional[requests.Session] = None


def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=_DEFAULT_RETRIES,
        backoff_factor=_DEFAULT_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PUT", "DELETE", "PATCH"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    # Немного безопасных заголовков по умолчанию
    s.headers.update({"User-Agent": "crypto-ai-bot/1.0"})
    return s


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def http_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[bool, Any]:
    """
    Возвращает (ok, payload|error).
    Если ok=True — payload это JSON (если распарсился) либо текст.
    Если ok=False — error это словарь с полями {"error", "status", "text"} либо строка-исключение.
    """
    try:
        sess = _get_session()
        resp = sess.get(url, params=params, headers=headers, timeout=timeout or _DEFAULT_TIMEOUT)
        if 200 <= resp.status_code < 300:
            try:
                return True, resp.json()
            except ValueError:
                return True, resp.text
        return False, {"error": "http_error", "status": resp.status_code, "text": resp.text}
    except Exception as e:
        return False, str(e)


def http_post(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    json: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Tuple[bool, Any]:
    """
    Возвращает (ok, payload|error) по тем же правилам, что http_get.
    """
    try:
        sess = _get_session()
        resp = sess.post(url, data=data, json=json, headers=headers, timeout=timeout or _DEFAULT_TIMEOUT)
        if 200 <= resp.status_code < 300:
            try:
                return True, resp.json()
            except ValueError:
                return True, resp.text
        return False, {"error": "http_error", "status": resp.status_code, "text": resp.text}
    except Exception as e:
        return False, str(e)
