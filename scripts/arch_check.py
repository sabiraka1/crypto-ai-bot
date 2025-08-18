"""
Проверка архитектурных правил:
- Domain не импортирует Infrastructure.
- Запрещён прямой доступ к ос.переменным вне core/settings.py.
- Запрещён прямой requests вне utils/http_client.py.
- Поиск циклических залежимостей между внутренними модулями.

Запуск:  python -m scripts.arch_check
Код выхода 0/1.
"""
from __future__ import annotations
import os, sys, ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]           # repo/
SRC  = ROOT / "src" / "crypto_ai_bot"                # src/crypto_ai_bot
PKG  = "crypto_ai_bot"

# ---- классификация слоёв ----
DOMAIN_DIRS = [
    SRC / "core" / "risk",
    SRC / "core" / "signals",
    SRC / "core" / "positions",
    SRC / "core" / "indicators",
    SRC / "core" / "types",
]
INFRA_PREFIXES = [
    f"{PKG}.app",
    f"{PKG}.utils",
    f"{PKG}.core.storage",
    f"{PKG}.core.brokers",
]

ALLOWED_ENV_FILES = {
    (SRC / "core" / "settings.py").as_posix(),
}
ALLOWED_REQUESTS_FILES = {
    (SRC / "utils" / "http_client.py").as_posix(),
}

def _py_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if p.name != "__init__.py"]

def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent)  # src/...
    parts = list(rel.with_suffix("").parts)
    # drop 'src'
    if parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)

def _parse_imports(path: Path) -> Set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out.add(n.module)
    return out

def _is_domain_file(path: Path) -> bool:
    p = path.resolve()
    return any(str(p).startswith(str(d.resolve()) + os.sep) for d in DOMAIN_DIRS)

def _violates_domain_imports(src_path: Path, imported: str) -> bool:
    if not _is_domain_file(src_path):
        return False
    return any(imported == pref or imported.startswith(pref + ".") for pref in INFRA_PREFIXES)

def _scan_env_usage(path: Path) -> bool:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    return ("os.getenv(" in txt) or ("os.environ[" in txt)

def _scan_requests_import(path: Path) -> bool:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    return ("import requests" in txt) or ("from requests" in txt)

def _build_graph(files: List[Path]) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {}
    for f in files:
        mod = _module_name(f)
        graph.setdefault(mod, set())
        for imp in _parse_imports(f):
            if imp.startswith(PKG + "."):
                graph[mod].add(imp)
    return graph

def _find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    sys.setrecursionlimit(10000)
    visited: Dict[str, int] = {}  # 0=unseen, 1=stack, 2=done
    stack: List[str] = []
    cycles: List[List[str]] = []

    def dfs(u: str):
        visited[u] = 1
        stack.append(u)
        for v in graph.get(u, ()):
            if v not in graph:
                continue
            state = visited.get(v, 0)
            if state == 0:
                dfs(v)
            elif state == 1:
                # цикл: срез до v
                try:
                    i = stack.index(v)
                    cycles.append(stack[i:] + [v])
                except ValueError:
                    pass
        stack.pop()
        visited[u] = 2

    for node in graph:
        if visited.get(node, 0) == 0:
            dfs(node)
    return cycles

def main() -> int:
    files = _py_files(SRC)
    violations: List[str] = []

    # 1) Domain -> Infra запрет
    for f in files:
        imports = _parse_imports(f)
        for imp in imports:
            if _violates_domain_imports(f, imp):
                violations.append(f"[LAYER] {f} imports {imp} (domain must not depend on infra)")

    # 2) os.getenv / os.environ вне settings.py
    for f in files:
        if f.as_posix() in ALLOWED_ENV_FILES:
            continue
        if _scan_env_usage(f):
            violations.append(f"[ENV] {f} uses os.getenv/environ (only core/settings.py allowed)")

    # 3) прямой requests во всех местах, кроме utils/http_client.py
    for f in files:
        if f.as_posix() in ALLOWED_REQUESTS_FILES:
            continue
        if _scan_requests_import(f):
            violations.append(f"[HTTP] {f} imports requests (use utils/http_client.py)")

    # 4) циклы импортов
    graph = _build_graph(files)
    cycles = _find_cycles(graph)
    for c in cycles:
        violations.append("[CYCLE] " + " -> ".join(c))

    if violations:
        print("ARCH CHECK FAILED:")
        for v in violations:
            print(" -", v)
        return 1

    print("ARCH CHECK OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
