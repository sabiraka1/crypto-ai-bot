from __future__ import annotations

"""
core/positions/manager.py — единая точка управления позициями.
Цели:
- Чистый API для use-cases: open / partial_close / close / get_snapshot / get_pnl / get_exposure
- Не зависит от конкретной БД: репозитории прокидываются через configure_repositories()
- Если репозитории не сконфигурированы — работает безопасный in-memory fallback (для локальных тестов)
- Деньги — Decimal, время — UTC-aware ISO8601
"""

from dataclasses import asdict
from decimal import Decimal
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

try:
    # Контракты типов, если есть
    from crypto_ai_bot.core.types.trading import Position  # type: ignore
except Exception:
    Position = None  # будем работать со словарями, если моделей нет

# Репозитории (инжектируются один раз при старте приложения)
_POS_REPO = None
_TRADES_REPO = None
_AUDIT_REPO = None

_lock = RLock()
_MEM_POS: Dict[str, Dict[str, Any]] = {}  # pos_id -> position dict


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure_repositories(*, positions_repo=None, trades_repo=None, audit_repo=None) -> None:
    """
    Вызвать один раз при старте приложения (server.py) для подключения БД-репозиториев.
    """
    global _POS_REPO, _TRADES_REPO, _AUDIT_REPO
    with _lock:
        if positions_repo is not None:
            _POS_REPO = positions_repo
        if trades_repo is not None:
            _TRADES_REPO = trades_repo
        if audit_repo is not None:
            _AUDIT_REPO = audit_repo


def _new_pos_id(symbol: str) -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"{symbol.replace('/', '_')}:{ts}"


def open(*, symbol: str, side: str, size: Decimal, sl: Optional[Decimal] = None, tp: Optional[Decimal] = None) -> Dict[str, Any]:
    """
    Идемпотентность обеспечивается на уровне use-case через IdempotencyRepository.
    Здесь — атомарное создание/апдейт позиции.
    Возвращает простой dict (сериализуемый).
    """
    pos_id = _new_pos_id(symbol)
    now = _utcnow_iso()
    pos_dict: Dict[str, Any] = {
        "id": pos_id,
        "symbol": symbol,
        "side": side,
        "size": str(size),
        "sl": str(sl) if sl is not None else None,
        "tp": str(tp) if tp is not None else None,
        "status": "open",
        "opened_at": now,
        "closed_at": None,
        "avg_price": None,  # цену заполняет слой исполнения/брокер при наличии
    }

    with _lock:
        if _POS_REPO is not None and hasattr(_POS_REPO, "upsert"):
            try:
                if Position is not None:
                    _POS_REPO.upsert(Position(**pos_dict))  # type: ignore[arg-type]
                else:
                    _POS_REPO.upsert(pos_dict)  # type: ignore[attr-defined]
            except Exception:
                # не роняем — дублируем в память
                _MEM_POS[pos_id] = pos_dict.copy()
        else:
            _MEM_POS[pos_id] = pos_dict.copy()

        if _AUDIT_REPO is not None and hasattr(_AUDIT_REPO, "append"):
            try:
                _AUDIT_REPO.append({
                    "ts": now,
                    "type": "position_open",
                    "position_id": pos_id,
                    "symbol": symbol,
                    "side": side,
                    "size": str(size),
                })
            except Exception:
                pass

    return pos_dict


def partial_close(pos_id: str, size: Decimal) -> Dict[str, Any]:
    """
    Частичное закрытие позиции: уменьшает размер, не уходит в отрицательные значения.
    Если размер становится 0 — статус 'closed' и метка времени закрытия.
    """
    now = _utcnow_iso()
    with _lock:
        pos = None
        # пробуем из репозитория (если есть get_by_id)
        if _POS_REPO is not None and hasattr(_POS_REPO, "get_by_id"):
            try:
                obj = _POS_REPO.get_by_id(pos_id)
                if obj:
                    if hasattr(obj, "__dict__"):
                        pos = dict(obj.__dict__)
                    elif hasattr(obj, "model_dump"):
                        pos = obj.model_dump()
                    elif isinstance(obj, dict):
                        pos = obj
            except Exception:
                pos = None
        # fallback на память
        if pos is None:
            pos = _MEM_POS.get(pos_id)
        if pos is None:
            return {"status": "not_found", "position_id": pos_id}

        cur_size = Decimal(str(pos.get("size", "0")))
        new_size = cur_size - size
        if new_size <= Decimal("0"):
            pos["size"] = "0"
            pos["status"] = "closed"
            pos["closed_at"] = now
        else:
            pos["size"] = str(new_size)

        # сохранить
        if _POS_REPO is not None and hasattr(_POS_REPO, "upsert"):
            try:
                if Position is not None:
                    _POS_REPO.upsert(Position(**pos))  # type: ignore[arg-type]
                else:
                    _POS_REPO.upsert(pos)  # type: ignore[attr-defined]
            except Exception:
                _MEM_POS[pos_id] = pos.copy()
        else:
            _MEM_POS[pos_id] = pos.copy()

        if _AUDIT_REPO is not None and hasattr(_AUDIT_REPO, "append"):
            try:
                _AUDIT_REPO.append({
                    "ts": now,
                    "type": "position_partial_close",
                    "position_id": pos_id,
                    "size": str(size),
                    "new_size": pos["size"],
                })
            except Exception:
                pass

    return {"status": "ok", "position": pos}


def close(pos_id: str) -> Dict[str, Any]:
    """
    Полное закрытие позиции.
    """
    now = _utcnow_iso()
    with _lock:
        pos = None
        if _POS_REPO is not None and hasattr(_POS_REPO, "get_by_id"):
            try:
                obj = _POS_REPO.get_by_id(pos_id)
                if obj:
                    if hasattr(obj, "__dict__"):
                        pos = dict(obj.__dict__)
                    elif hasattr(obj, "model_dump"):
                        pos = obj.model_dump()
                    elif isinstance(obj, dict):
                        pos = obj
            except Exception:
                pos = None
        if pos is None:
            pos = _MEM_POS.get(pos_id)
        if pos is None:
            return {"status": "not_found", "position_id": pos_id}

        pos["size"] = "0"
        pos["status"] = "closed"
        pos["closed_at"] = now

        if _POS_REPO is not None and hasattr(_POS_REPO, "upsert"):
            try:
                if Position is not None:
                    _POS_REPO.upsert(Position(**pos))  # type: ignore[arg-type]
                else:
                    _POS_REPO.upsert(pos)  # type: ignore[attr-defined]
            except Exception:
                _MEM_POS[pos_id] = pos.copy()
        else:
            _MEM_POS[pos_id] = pos.copy()

        if _AUDIT_REPO is not None and hasattr(_AUDIT_REPO, "append"):
            try:
                _AUDIT_REPO.append({
                    "ts": now,
                    "type": "position_close",
                    "position_id": pos_id,
                })
            except Exception:
                pass

    return {"status": "ok", "position": pos}


def get_snapshot() -> Dict[str, Any]:
    """
    Простая сводка по открытым позициям.
    """
    with _lock:
        opens: List[Dict[str, Any]] = []

        if _POS_REPO is not None and hasattr(_POS_REPO, "get_open"):
            try:
                rows = _POS_REPO.get_open()
                for obj in rows:
                    if hasattr(obj, "__dict__"):
                        opens.append(dict(obj.__dict__))
                    elif hasattr(obj, "model_dump"):
                        opens.append(obj.model_dump())
                    elif isinstance(obj, dict):
                        opens.append(obj)
            except Exception:
                # fallback к памяти
                opens = [v for v in _MEM_POS.values() if v.get("status") == "open"]
        else:
            opens = [v for v in _MEM_POS.values() if v.get("status") == "open"]

        total_size = sum(Decimal(str(p.get("size", "0"))) for p in opens)
        return {"open_positions": opens, "total_size": str(total_size)}


def get_pnl() -> Decimal:
    """
    Возвращает совокупный PnL (plug — 0), пока нет цен/трека.
    Если появится связка с tracker/ценой — тут будем считать.
    """
    return Decimal("0")


def get_exposure() -> Decimal:
    """
    Возвращает текущую экспозицию (plug — 0).
    Для точного подсчёта нужен доступ к mark price/last price и валюте котировки.
    """
    return Decimal("0")
