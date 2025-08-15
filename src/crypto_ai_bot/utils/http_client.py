# src/crypto_ai_bot/utils/http_client.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def _session(timeout=10, retries=2):
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=0.3, status_forcelist=[429, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))

    # подмешиваем дефолтный timeout
    _orig = s.request
    def _req(method, url, **kw):
        if "timeout" not in kw:
            kw["timeout"] = timeout
        return _orig(method, url, **kw)
    s.request = _req
    return s

_s = _session()

def http_get(url: str, **kw):
    return _s.get(url, **kw)

def http_post(url: str, **kw):
    return _s.post(url, **kw)
