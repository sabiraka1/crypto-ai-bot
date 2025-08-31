from __future__ import annotations

import contextlib
import contextvars
import uuid
from typing import Iterator, Optional

_cid: contextvars.ContextVar[str | None] = contextvars.ContextVar("cid", default=None)

def new_cid() -> str:
    return uuid.uuid4().hex

def get_cid() -> Optional[str]:
    return _cid.get()

def set_cid(value: Optional[str]) -> None:
    _cid.set(value)

@contextlib.contextmanager
def cid_context(value: Optional[str] = None) -> Iterator[None]:
    token = _cid.set(value or new_cid())
    try:
        yield
    finally:
        _cid.reset(token)
