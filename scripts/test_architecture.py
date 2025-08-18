import ast
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src" / "crypto_ai_bot"
PKG  = "crypto_ai_bot"

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
ALLOWED_ENV_FILES = {(SRC / "core" / "settings.py").as_posix()}
ALLOWED_REQUESTS_FILES = {(SRC / "utils" / "http_client.py").as_posix()}

def _py_files(root: Path):
    for p in root.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        yield p

def _parse_imports(p: Path):
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out.add(n.module)
    return out

def _is_domain_file(p: Path) -> bool:
    p = p.resolve()
    return any(str(p).startswith(str(d.resolve()) + os.sep) for d in DOMAIN_DIRS)

def test_domain_does_not_import_infra():
    bad = []
    for f in _py_files(SRC):
        if not _is_domain_file(f):
            continue
        for imp in _parse_imports(f):
            if any(imp == pref or imp.startswith(pref + ".") for pref in INFRA_PREFIXES):
                bad.append((f, imp))
    assert not bad, "Domain must not import infra:\n" + "\n".join(f" - {f} -> {imp}" for f, imp in bad)

def test_no_direct_env_usage_outside_settings():
    bad = []
    for f in _py_files(SRC):
        if f.as_posix() in ALLOWED_ENV_FILES:
            continue
        txt = f.read_text(encoding="utf-8", errors="ignore")
        if ("os.getenv(" in txt) or ("os.environ[" in txt):
            bad.append(f)
    assert not bad, "os.getenv/environ only allowed in core/settings.py:\n" + "\n".join(f" - {p}" for p in bad)

def test_no_requests_import_outside_http_client():
    bad = []
    for f in _py_files(SRC):
        if f.as_posix() in ALLOWED_REQUESTS_FILES:
            continue
        txt = f.read_text(encoding="utf-8", errors="ignore")
        if ("import requests" in txt) or ("from requests" in txt):
            bad.append(f)
    assert not bad, "Use utils/http_client.py (no direct requests):\n" + "\n".join(f" - {p}" for p in bad)
