#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Текстовые расширения
TEXT_EXTS = {
    ".py", ".md", ".txt", ".ini", ".toml", ".yml", ".yaml", ".json", ".cfg",
    ".env", ".rst", ".log",
}

# Подозрительные символы, часто встречающиеся при mojibake
SUSPECT_CHARS = "ÐÑÃÂРС"
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
# пары вида 'Р'/'С' + НЕкириллица (частая картина: 'С‚', 'Р°' и пр.)
RS_NON_CYR = re.compile(r"[РС](?![\u0400-\u04FF]).")

@dataclass
class Change:
    bom_removed: bool
    recoded: str | None
    normalized_newlines: bool

def _score(text: str) -> tuple[int, int, int]:
    """Возвращает метрику качества: (sus_total, rs_non_cyr, cyr_count). Меньше/меньше/больше — лучше."""
    sus_total = sum(text.count(ch) for ch in SUSPECT_CHARS)
    rs_nc = len(RS_NON_CYR.findall(text))
    cyr = len(CYRILLIC_RE.findall(text))
    return sus_total, rs_nc, cyr

def _choose_best(original: str) -> tuple[str, str | None]:
    """Всегда пробуем 2 кандидата и выбираем лучший относительно original."""
    cand = [("orig", original), ("latin1->utf8", original), ("cp1251->utf8_roundtrip", original)]
    # Кандидаты перекодировки
    try:
        cand[1] = (cand[1][0], original.encode("latin1", "strict").decode("utf-8", "strict"))
    except Exception:
        pass
    try:
        cand[2] = (cand[2][0], original.encode("cp1251", "strict").decode("utf-8", "strict"))
    except Exception:
        pass

    base = _score(original)
    best = (10**9, 10**9, -10**9, "orig", original)  # (sus, rs_nc, -cyr, tag, text)

    for tag, txt in cand:
        s = _score(txt)
        candidate = (s[0], s[1], -s[2], tag, txt)
        if candidate < best:
            best = candidate

    tag, txt = best[3], best[4]
    if tag == "orig":
        return original, None
    return txt, tag

def guess_and_fix_text(data: bytes, suffix: str, *, aggressive: bool, force: bool) -> tuple[str, Change, bool]:
    bom_removed = False
    if data.startswith(b"\xef\xbb\xbf"):
        bom_removed = True
        data = data[3:]

    # Базовая попытка как UTF-8, иначе cp1251
    try:
        s = data.decode("utf-8", "strict")
        recoded = None
    except UnicodeDecodeError:
        s = data.decode("cp1251", "strict")
        recoded = "cp1251->utf8"

    original = s

    # Выбор лучшего кандидата относительно original
    fixed_text, tag = _choose_best(s)

    # Требуем ощутимого улучшения (снижение «мусора»/рост кириллицы)
    sus0, rs0, cyr0 = _score(original)
    sus1, rs1, cyr1 = _score(fixed_text)
    improved = (sus1 < sus0) or (rs1 < rs0) or (cyr1 > cyr0)
    # порог: хотя бы 15% улучшения в одном из показателей (в aggressive — 5%)
    thr = 0.15 if not aggressive else 0.05
    def rel_improved(a: int, b: int, bigger_is_better: bool) -> bool:
        if a == b:
            return False
        if bigger_is_better:
            return (b - a) / max(1, a) >= thr
        return (a - b) / max(1, a) >= thr

    accept = (
        rel_improved(sus0, sus1, False) or
        rel_improved(rs0, rs1, False) or
        rel_improved(cyr0, cyr1, True)
    )

    if improved and accept:
        s = fixed_text
        recoded = tag if tag else recoded

    # Нормализация переводов строк и финальный \n
    normalized_newlines = ("\r" in s) or (not s.endswith("\n"))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if not s.endswith("\n"):
        s += "\n"

    # Для .py — AST-проверка; можно пропустить флагом --force
    if suffix == ".py" and not force:
        try:
            ast.parse(s)
        except SyntaxError:
            # не портим код
            return original, Change(bom_removed, recoded, normalized_newlines), False

    changed = (s != original) or bom_removed or (recoded is not None)
    return s, Change(bom_removed, recoded, normalized_newlines), changed

def iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in TEXT_EXTS:
                yield p

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="внести изменения (по умолчанию dry-run)")
    ap.add_argument("--root", default=".", help="корень поиска (по умолчанию текущая папка)")
    ap.add_argument("--aggressive", action="store_true", help="агрессивней выбирать перекодировку (порог улучшения ниже)")
    ap.add_argument("--force", action="store_true", help="для .py не проверять AST (используй осторожно)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    # Сначала src/, затем корень (на случай конфигов)
    files = list(iter_files([root / "src", root]))
    seen: set[Path] = set()
    total = 0

    for p in files:
        if p in seen:
            continue
        seen.add(p)

        try:
            data = p.read_bytes()
        except Exception:
            continue

        text_fixed, meta, changed = guess_and_fix_text(
            data, p.suffix.lower(), aggressive=args.aggressive, force=args.force
        )

        if not changed:
            continue

        total += 1
        print(f"[{'APPLY' if args.apply else 'DRY'}] {p}")
        if meta.bom_removed:
            print("  - remove BOM")
        if meta.recoded:
            print(f"  - recode: {meta.recoded}")
        if meta.normalized_newlines:
            print("  - normalize newlines -> LF; ensure trailing newline")

        if args.apply:
            # бэкап рядом
            bak = p.with_suffix(p.suffix + ".bak")
            try:
                if not bak.exists():
                    bak.write_bytes(data)
            except Exception:
                pass
            p.write_text(text_fixed, encoding="utf-8")

    print(f"\nDone. Changed: {total} file(s). Use --apply to write changes." if not args.apply else
          f"\nDone. Wrote changes to {total} file(s).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
