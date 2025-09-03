from __future__ import annotations

from collections.abc import Iterator
import contextlib
import contextvars
import uuid

_cid: contextvars.ContextVar[str | None] = contextvars.ContextVar("cid", default=None)


def new_cid() -> str:
    return uuid.uuid4().hex


def get_cid() -> str | None:
    return _cid.get()


def set_cid(value: str | None) -> None:
    _cid.set(value)


@contextlib.contextmanager
def cid_context(value: str | None = None) -> Iterator[None]:
    token = _cid.set(value or new_cid())
    try:
        yield
    finally:
        _cid.reset(token)
