# -*- coding: utf-8 -*-
from __future__ import annotations
import requests

# Единый клиент с короткими помощниками. При желании сюда добавим retry/timeout по умолчанию.

def http_get(url: str, timeout: float = 10.0, **kwargs) -> requests.Response:
    return requests.get(url, timeout=timeout, **kwargs)

def http_post(url: str, timeout: float = 10.0, **kwargs) -> requests.Response:
    return requests.post(url, timeout=timeout, **kwargs)
