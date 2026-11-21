"""Layer boundaries: front/, backend/ and job/ deploy separately.

front   -> Vercel project at the repo root (static build of front/)
backend -> its own Vercel project (root directory backend/), serves /api/*
job     -> runs on the Mac (job/mac/jobs.conf), writes the radar tables
db      -> Supabase migrations shared by all three

A layer may read the database contract (db/) but never import another
layer's code, or its deploy would silently miss files.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|require\(\s*)['"](\.{1,2}/[^'"]+)['"]""")


def _relative_imports(layer: str, suffixes: set[str]):
    base = ROOT / layer
    for path in base.rglob("*"):
        if path.suffix not in suffixes or "node_modules" in path.parts or "dist" in path.parts:
            continue
        for target in JS_IMPORT.findall(path.read_text(encoding="utf-8", errors="ignore")):
            yield path, (path.parent / target).resolve()


def test_backend_code_imports_nothing_outside_backend():
    for path, target in _relative_imports("backend/api", {".js", ".mjs"}):
        assert (ROOT / "backend") in target.parents, f"{path} imports {target}"


def test_front_code_imports_nothing_outside_front():
    for path, target in _relative_imports("front/src", {".ts", ".tsx", ".js"}):
        assert (ROOT / "front") in target.parents, f"{path} imports {target}"


def test_backend_python_functions_do_not_import_the_job_layer():
    for path in (ROOT / "backend" / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from scripts" not in text and "import scripts" not in text, path


def test_pre_market_contract_copies_are_identical():
    """The browser and the API validate the same payload shape."""
    front = (ROOT / "front" / "src" / "lib" / "preMarketContract.js").read_text(encoding="utf-8")
    backend = (ROOT / "backend" / "api" / "_lib" / "preMarketContract.js").read_text(encoding="utf-8")
    assert front == backend, "edit both copies of preMarketContract.js together"


def test_old_root_layout_is_gone():
    for name in ("api", "scripts", "src", "assets", "supabase", "ops", "data", "config", "requirements.txt", "package.json"):
        assert not (ROOT / name).exists(), f"{name} belongs in a layer folder now"
