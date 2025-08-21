## `core/validators/dto.py`
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple
from ...utils.exceptions import ValidationError
from ...utils.ids import sanitize_ascii
ALLOWED_SIDES = {"buy", "sell"}
def ensure_side(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("side must be a string")
    s = value.strip().lower()
    if s not in ALLOWED_SIDES:
        raise ValidationError("side must be 'buy' or 'sell'")
    return s
def ensure_amount(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError("amount must be a valid number")
    if d <= 0:
        raise ValidationError("amount must be > 0")
    return d
def ensure_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValidationError("symbol must be a non-empty string")
    if "/" not in symbol:
        raise ValidationError("symbol must contain '/' (e.g., 'BTC/USDT')")
    return symbol
def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
def validate_ticker_dto(dto: Any) -> List[str]:
    errors: List[str] = []
    symbol = _get(dto, "symbol")
    last = _get(dto, "last")
    bid = _get(dto, "bid")
    ask = _get(dto, "ask")
    ts = _get(dto, "timestamp")
    if not isinstance(symbol, str) or not symbol:
        errors.append("TickerDTO.symbol must be non-empty string")
    for name, v in ("last", last), ("bid", bid), ("ask", ask):
        try:
            _ = float(v)
        except Exception:
            errors.append(f"TickerDTO.{name} must be a number")
    if not isinstance(ts, int) or ts <= 0:
        errors.append("TickerDTO.timestamp must be positive int milliseconds")
    return errors
def validate_order_request(symbol: str, side: str, amount: Any) -> Tuple[str, str, Decimal]:
    """Normalize and validate order request fields (raise on error)."""
    sym = ensure_symbol(symbol)
    sd = ensure_side(side)
    amt = ensure_amount(amount)
    return sym, sd, amt
def validate_client_order_id(client_order_id: str, *, max_len: int = 64) -> None:
    if not isinstance(client_order_id, str) or not client_order_id:
        raise ValidationError("client_order_id must be a non-empty string")
    safe = sanitize_ascii(client_order_id)
    if safe != client_order_id:
        raise ValidationError("client_order_id must be ASCII-safe [a-z0-9-]")
    if len(client_order_id) > max_len:
        raise ValidationError(f"client_order_id must be <= {max_len} characters for this exchange")