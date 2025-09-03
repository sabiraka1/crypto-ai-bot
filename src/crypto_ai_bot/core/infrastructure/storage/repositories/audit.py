from __future__ import annotations

import json
import sqlite3
from typing import Any


def _json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"


class AuditRepo:
    """
    ДћВђГ‘Ж’ДћВґДћВёГ‘вЂљ-Г‘в‚¬ДћВµДћВїДћВѕДћВ·ДћВёГ‘вЂљДћВѕГ‘в‚¬ДћВёДћВ№ ДћВґДћВ»Г‘ВЏ ДћВ·ДћВ°ДћВїДћВёГ‘ВЃДћВё Г‘ВЃДћВѕДћВ±Г‘вЂ№Г‘вЂљДћВёДћВ№ ДћВІ Г‘вЂљДћВ°ДћВ±ДћВ»ДћВёГ‘вЂ Г‘Ж’ `audit`.
    ДћВЎДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВј ДћВё Г‘ВЃ .write(...), ДћВё Г‘ВЃДћВѕ Г‘ВЃГ‘вЂљДћВ°Г‘в‚¬Г‘вЂ№ДћВј .add(...).
    ДћВћДћВ¶ДћВёДћВґДћВ°ДћВµГ‘вЂљ SQLite-ДћВїДћВѕДћВґДћВѕДћВ±ДћВЅГ‘вЂ№ДћВ№ connection (conn.cursor().execute(...)).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:  # ДћЛњГ‘ВЃДћВїГ‘в‚¬ДћВ°ДћВІДћВ»ДћВµДћВЅДћВѕ: ДћВґДћВѕДћВ±ДћВ°ДћВІДћВ»ДћВµДћВЅ Г‘вЂљДћВёДћВї
        self._conn = conn

    def write(self, event: str, payload: dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO audit (event, payload_json, ts_ms) "
            "VALUES (?, json(?), CAST(STRFTIME('%s','now') AS INTEGER)*1000)",
            (event, _json_dumps_safe(payload)),
        )
        self._conn.commit()

    # ДћвЂќДћВ»Г‘ВЏ ДћВѕДћВ±Г‘в‚¬ДћВ°Г‘вЂљДћВЅДћВѕДћВ№ Г‘ВЃДћВѕДћВІДћВјДћВµГ‘ВЃГ‘вЂљДћВёДћВјДћВѕГ‘ВЃГ‘вЂљДћВё Г‘ВЃДћВѕ Г‘ВЃГ‘вЂљДћВ°Г‘в‚¬Г‘вЂ№ДћВј ДћВёДћВјДћВµДћВЅДћВµДћВј:
    def add(self, event: str, payload: dict[str, Any]) -> None:
        self.write(event, payload)
