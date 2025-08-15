# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests

log = logging.getLogger(__name__)

@dataclass
class HttpClient:
    timeout: float = 10.0
    retries: int = 2

    def _req(self, method: str, url: str, **kw) -> requests.Response:
        last_err: Optional[Exception] = None
        for i in range(self.retries + 1):
            try:
                resp = requests.request(method, url, timeout=self.timeout, **kw)
                return resp
            except Exception as e:
                last_err = e
                log.warning("HTTP %s %s failed (%s/%s): %s", method, url, i+1, self.retries, e)
        assert last_err
        raise last_err

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        r = self._req("GET", url, headers=headers)
        r.raise_for_status()
        return r.json()

    def post_json(self, url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        r = self._req("POST", url, data=json.dumps(payload), headers=h)
        r.raise_for_status()
        return r.json()

    def post_multipart(self, url: str, files: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = self._req("POST", url, files=files, data=data)
        r.raise_for_status()
        return r.json()

_client: Optional[HttpClient] = None

def get_http_client() -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient()
    return _client

