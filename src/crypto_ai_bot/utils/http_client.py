from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
_DEFAULT_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
_DEFAULT_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.5"))

@dataclass
class HttpClient:
    timeout: float = _DEFAULT_TIMEOUT
    retries: int = _DEFAULT_RETRIES
    backoff: float = _DEFAULT_BACKOFF

    def _request(self, method: str, url: str, **kwargs) -> Tuple[int, str]:
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.request(method, url, timeout=self.timeout, **kwargs)
                return resp.status_code, resp.text
            except Exception as e:
                last_exc = e
                logger.warning("HTTP %s %s failed (%s/%s): %s",
                               method, url, attempt + 1, self.retries + 1, e)
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
        # если не получилось
        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP request failed without exception")

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        code, text = self._request("GET", url, headers=headers)
        try:
            return json.loads(text)
        except Exception:
            logger.error("GET %s → %s, not JSON: %s", url, code, text[:300])
            return {"ok": False, "status": code, "text": text}

    def post_json(self, url: str, json_body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        code, text = self._request("POST", url, json=json_body, headers=headers)
        try:
            return json.loads(text)
        except Exception:
            logger.error("POST %s → %s, not JSON: %s", url, code, text[:300])
            return {"ok": False, "status": code, "text": text}

    def post_multipart(self, url: str, files: Dict[str, Any], data: Optional[Dict[str, Any]] = None,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        code, text = self._request("POST", url, files=files, data=data, headers=headers)
        try:
            return json.loads(text)
        except Exception:
            logger.error("POST-multipart %s → %s, not JSON: %s", url, code, text[:300])
            return {"ok": False, "status": code, "text": text}

# фабрика один раз
_client: Optional[HttpClient] = None
def get_http_client() -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient()
    return _client

# --- ТОНКИЕ ОБЁРТКИ (чтобы не менять импорты в server.py и др.) ---

def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_http_client().get_json(url, headers=headers)

def http_post(url: str, json_body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_http_client().post_json(url, json_body, headers=headers)
