from __future__ import annotations
import os, sqlite3, time
from contextlib import contextmanager
from typing import Iterator, Dict, Any, Optional

try:
    from crypto_ai_bot.utils import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **k): pass
        def observe(self, *a, **k): pass
        def export(self): return ""
    metrics = _Dummy()  # type: ignore

def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con

@contextmanager
def in_txn(con: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE;")
        yield cur
        cur.execute("COMMIT;")
    except Exception:
        cur.execute("ROLLBACK;")
        raise
    finally:
        cur.close()

def _db_file_path(con: sqlite3.Connection) -> Optional[str]:
    try:
        row = con.execute("PRAGMA database_list;").fetchone()
        if row and len(row) >= 3:
            return row[2]
        return None
    except Exception:
        return None

def get_db_stats(con: sqlite3.Connection) -> Dict[str, Any]:
    try:
        row_pc = con.execute("PRAGMA page_count;").fetchone()
        row_ps = con.execute("PRAGMA page_size;").fetchone()
        row_fl = con.execute("PRAGMA freelist_count;").fetchone()
        page_count = int(row_pc[0] if row_pc else 0)
        page_size = int(row_ps[0] if row_ps else 4096)
        freelist = int(row_fl[0] if row_fl else 0)
        size_bytes_calc = page_count * page_size
        fp = _db_file_path(con)
        size_bytes_real = os.path.getsize(fp) if fp and os.path.exists(fp) else size_bytes_calc
        frag_pct = float(freelist / page_count) if page_count > 0 else 0.0
        return {
            "page_count": page_count,
            "page_size": page_size,
            "freelist": freelist,
            "size_bytes": size_bytes_real,
            "fragmentation_pct": frag_pct,
            "file_path": fp,
        }
    except Exception as e:  # pragma: no cover
        return {"error": f"{type(e).__name__}: {e}"}

def _ensure_meta(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS _meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);"
    )

def _get_meta(con: sqlite3.Connection, key: str, default: str = "0") -> str:
    _ensure_meta(con)
    row = con.execute("SELECT v FROM _meta WHERE k=?;", (key,)).fetchone()
    return row[0] if row else default

def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    _ensure_meta(con)
    con.execute("INSERT INTO _meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v;", (key, value))

def maintenance_maybe_vacuum_analyze(
    con: sqlite3.Connection,
    *,
    max_fragmentation_pct: float = 0.15,
    min_vacuum_bytes: int = 50 * 1024 * 1024,  # 50MB
    min_hours_between_vacuum: int = 12,
    min_hours_between_analyze: int = 6,
) -> Dict[str, Any]:
    """Heuristic DB maintenance with throttling.

    Returns dict with actions {'vacuum': bool, 'analyze': bool, 'stats': {...}}.

    """
    stats = get_db_stats(con)
    now = int(time.time())

    last_vac = int(_get_meta(con, "last_vacuum_ts", "0"))
    last_an = int(_get_meta(con, "last_analyze_ts", "0"))
    hours_since_vac = (now - last_vac) / 3600 if last_vac else 1e9
    hours_since_an = (now - last_an) / 3600 if last_an else 1e9

    frag = float(stats.get("fragmentation_pct", 0.0))
    size_b = int(stats.get("size_bytes", 0))

    do_vac = (frag >= max_fragmentation_pct) and (size_b >= min_vacuum_bytes) and (hours_since_vac >= min_hours_between_vacuum)
    do_an  = (hours_since_an >= min_hours_between_analyze)

    if do_an:
        try:
            con.execute("ANALYZE;")
            _set_meta(con, "last_analyze_ts", str(now))
            try: metrics.inc("db_analyze_total", {"result": "ok"})
            except Exception: pass
        except Exception:  # pragma: no cover
            try: metrics.inc("db_analyze_total", {"result": "error"})
            except Exception: pass

    if do_vac:
        try:
            con.execute("VACUUM;")
            _set_meta(con, "last_vacuum_ts", str(now))
            try: metrics.inc("db_vacuum_total", {"result": "ok"})
            except Exception: pass
        except Exception:  # pragma: no cover
            try: metrics.inc("db_vacuum_total", {"result": "error"})
            except Exception: pass

    # export gauges
    try:
        metrics.observe("db_size_bytes_gauge", float(size_b))
        metrics.observe("db_fragmentation_pct_gauge", float(frag))
    except Exception:
        pass

    return {"vacuum": bool(do_vac), "analyze": bool(do_an), "stats": stats}
