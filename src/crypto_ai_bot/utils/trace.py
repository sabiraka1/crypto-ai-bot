from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import uuid

from crypto_ai_bot.utils.logging import get_correlation_id as _get_log_cid, set_correlation_id as _set_log_cid

_CID: ContextVar[str | None] = ContextVar("cid", default=None)


def set_cid(value: str | None) -> None:
    _CID.set(value)
    _set_log_cid(value)


def get_cid() -> str | None:
    v = _CID.get()
    return v if v else _get_log_cid()


@contextmanager
def cid_context(cid: str | None = None) -> Iterator[None]:
    """
    Контекст, который проставляет correlation id:
    - если cid не задан → генерируем uuid4().hex;
    - CID пробрасывается и в Json-логгер.
    """
    current = get_cid()
    new_value = cid or current or uuid.uuid4().hex
    token = _CID.set(new_value)
    _set_log_cid(new_value)
    try:
        yield
    finally:
        _CID.reset(token)
        _set_log_cid(current)
