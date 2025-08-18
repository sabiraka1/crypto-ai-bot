# -*- coding: utf-8 -*-
"""
Архитектурный смок-тест на соответствие контрольной карте (ALL-in-ONE).
Запуск:  PYTHONPATH=src python scripts/arch_smoke.py
Выход: код 0 при полном успехе, иначе 1; читабельные строки с ❌/✅.
"""
from __future__ import annotations
import os, sys, re, json, importlib, traceback
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
PKG = SRC / "crypto_ai_bot"

def fail(msg: str):
    print("❌", msg)
    return False

def ok(msg: str):
    print("✅", msg)
    return True

def grep_sources(pattern: str, exclude: List[Path]=None) -> List[Path]:
    rx = re.compile(pattern)
    hits: List[Path] = []
    for p in SRC.rglob("*.py"):
        if exclude and any(str(p).startswith(str(e)) for e in exclude):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if rx.search(txt):
            hits.append(p)
    return hits

def rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))

def main() -> int:
    os.environ.setdefault("PYTHONPATH", "src")
    errors: List[str] = []

    # --- 0) Базовая структура (ключевые файлы/папки) ---
    must_exist = [
        PKG/"app/server.py",
        PKG/"app/middleware.py",
        PKG/"app/bus_wiring.py",
        PKG/"app/adapters/telegram.py",
        PKG/"core/settings.py",
        PKG/"core/use_cases/evaluate.py",
        PKG/"core/use_cases/place_order.py",
        PKG/"core/signals/policy.py",
        PKG/"core/indicators/unified.py",
        PKG/"core/brokers",
        PKG/"core/events",
        PKG/"core/storage",
        PKG/"utils/metrics.py",
        PKG/"utils/http_client.py",
    ]
    ok_all = True
    for f in must_exist:
        if not f.exists():
            ok_all = False
            errors.append(f"Не найден ключевой файл/каталог: {rel(f)}")
    print(("✅" if ok_all else "❌"), "Структура: ключевые узлы присутствуют")
    # Не прерываемся — покажем максимум сигналов

    # --- 1) Импорт важнейших модулей (без падений) ---
    mods = [
        "crypto_ai_bot.core.events",
        "crypto_ai_bot.core.events.async_bus",
        "crypto_ai_bot.core.brokers.base",
        "crypto_ai_bot.core.storage",
        "crypto_ai_bot.core.storage.repositories.idempotency",
        "crypto_ai_bot.core.indicators.unified",
        "crypto_ai_bot.core.use_cases.evaluate",
        "crypto_ai_bot.app.server",
    ]
    for m in mods:
        try:
            importlib.import_module(m)
            ok(f"Импортируется: {m}")
        except Exception:
            errors.append(f"Импорт падает: {m}\n{traceback.format_exc()}")
            print("❌", f"Импорт падает: {m}")
            # продолжаем, чтобы собрать остальные сигналы

    # --- 2) Events: экспорт AsyncEventBus (+ алиас AsyncBus) ---
    try:
        ev = importlib.import_module("crypto_ai_bot.core.events")
        has_aeb = hasattr(ev, "AsyncEventBus")
        has_alias = hasattr(ev, "AsyncBus")
        if has_aeb and has_alias:
            ok("Events: AsyncEventBus (+ алиас AsyncBus) экспортируются")
        else:
            raise AssertionError(f"AsyncEventBus={has_aeb}, AsyncBus={has_alias}")
    except Exception as e:
        errors.append(f"Events export mismatch: {e}")
        print("❌", f"Events export mismatch: {e}")

    # --- 3) Storage: in_txn + SqliteUnitOfWork + connect ---
    try:
        st = importlib.import_module("crypto_ai_bot.core.storage")
        has_in_txn = hasattr(st, "in_txn")
        has_uow = hasattr(st, "SqliteUnitOfWork")
        has_connect = hasattr(st, "connect")
        if has_in_txn and has_uow and has_connect:
            ok("Storage: in_txn, SqliteUnitOfWork, connect — доступны")
        else:
            raise AssertionError(f"in_txn={has_in_txn}, SqliteUnitOfWork={has_uow}, connect={has_connect}")
    except Exception as e:
        errors.append(f"Storage export mismatch: {e}")
        print("❌", f"Storage export mismatch: {e}")

    # --- 4) Indicators: build_indicators присутствует ---
    try:
        ind = importlib.import_module("crypto_ai_bot.core.indicators.unified")
        if hasattr(ind, "build_indicators"):
            ok("Indicators: build_indicators — присутствует")
        else:
            raise AssertionError("Нет функции build_indicators")
    except Exception as e:
        errors.append(f"Indicators mismatch: {e}")
        print("❌", f"Indicators mismatch: {e}")

    # --- 5) Telegram команды: ровно финальный набор; нет /buy|/sell ---
    tg = PKG / "app/adapters/telegram.py"
    if tg.exists():
        txt = tg.read_text(encoding="utf-8", errors="ignore")
        need = {"/help", "/status", "/test", "/profit", "/eval", "/why"}
        present = {cmd for cmd in need if cmd in txt}
        extras_buy_sell = set()
        for bad in ("/buy", "/sell"):
            if bad in txt:
                extras_buy_sell.add(bad)
        if present == need and not extras_buy_sell:
            ok("Telegram: команды соответствуют (только /help /status /test /profit /eval /why)")
        else:
            if present != need:
                errors.append(f"Telegram: отсутствуют команды: {sorted(list(need - present))}")
                print("❌", f"Telegram: отсутствуют команды: {sorted(list(need - present))}")
            if extras_buy_sell:
                errors.append(f"Telegram: найдены запрещённые команды: {sorted(list(extras_buy_sell))}")
                print("❌", f"Telegram: найдены запрещённые команды: {sorted(list(extras_buy_sell))}")
    else:
        errors.append("Не найден adapters/telegram.py")
        print("❌", "Не найден adapters/telegram.py")

    # --- 6) Эндпоинты: /health, /metrics, /telegram, /status/extended ---
    try:
        server = importlib.import_module("crypto_ai_bot.app.server")
        app = getattr(server, "app", None)
        found = set()
        if app is not None:
            # Инспектируем Starlette маршруты
            try:
                from starlette.routing import Route
                for r in app.routes:
                    if isinstance(r, Route):
                        found.add(r.path)
            except Exception:
                pass

        # Если не получилось через объект — парсим исходник
        if not found:
            sfile = PKG / "app/server.py"
            stext = sfile.read_text(encoding="utf-8", errors="ignore")
            for p in ("/health", "/metrics", "/telegram", "/status/extended"):
                if p in stext:
                    found.add(p)

        missing = {"/health", "/metrics", "/status/extended"}
        # по /telegram допускаем вариант /telegram/webhook
        has_tel = any("/telegram" in x for x in found)
        if has_tel:
            ok_tel = True
        else:
            ok_tel = False

        miss = {p for p in missing if p not in found}
        if not miss and ok_tel:
            ok("Эндпоинты: /health, /metrics, /status/extended, /telegram — присутствуют")
        else:
            if miss:
                errors.append(f"Эндпоинты отсутствуют: {sorted(list(miss))}")
                print("❌", f"Эндпоинты отсутствуют: {sorted(list(miss))}")
            if not ok_tel:
                errors.append("Эндпоинт /telegram (или /telegram/webhook) не найден")
                print("❌", "Эндпоинт /telegram (или /telegram/webhook) не найден")
    except Exception as e:
        errors.append(f"Интроспекция server.py: {e}")
        print("❌", f"Интроспекция server.py: {e}")

    # --- 7) Политики: запрет прямого чтения ENV и прямого requests.* ---
    env_hits = grep_sources(r"os\.(environ\[|getenv\()", exclude=[PKG/"core/settings.py"])
    if env_hits:
        errors.append("Прямое чтение ENV вне core/settings.py:")
        for h in env_hits:
            print("❌", f"ENV outside settings: {rel(h)}")
    else:
        ok("Политика ENV: чтение ENV вне core/settings.py — не найдено")

    req_hits = grep_sources(r"\brequests\.", exclude=[PKG/"utils/http_client.py"])
    if req_hits:
        errors.append("Прямой вызов requests.* вне utils/http_client.py:")
        for h in req_hits:
            print("❌", f"requests.* outside http_client: {rel(h)}")
    else:
        ok("Политика HTTP: прямых requests.* вне utils/http_client.py — не найдено")

    # --- 8) Вывод / статус ---
    if errors:
        print("\n==== Сводка несоответствий ====")
        for e in errors:
            print("-", e)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
