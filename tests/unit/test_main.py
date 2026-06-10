"""Regression tests for the BYOC entrypoint (``main.py``).

ServiceMaker copies the project and runs ``python main.py`` against a venv that
may only contain the dependencies — not the ``multihop_eval`` package itself
(which lives under ``src/``). Previously this raised
``ModuleNotFoundError: No module named 'multihop_eval'`` when uvicorn tried to
import ``multihop_eval.web.service:app``. ``main.py`` now prepends ``src`` to
``sys.path`` so the import resolves regardless of how the venv was provisioned.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "main.py"
SRC_DIR = REPO_ROOT / "src"


def _load_main_module():
    """Import ``main.py`` fresh under a throwaway module name."""
    spec = importlib.util.spec_from_file_location("_byoc_main_under_test", MAIN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_main_puts_src_on_path() -> None:
    original = list(sys.path)
    # Simulate a venv where ``src`` is NOT already importable.
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != SRC_DIR.resolve()]
    try:
        _load_main_module()
        resolved = {Path(p).resolve() for p in sys.path}
        assert SRC_DIR.resolve() in resolved
    finally:
        sys.path[:] = original


def test_main_makes_package_importable() -> None:
    original = list(sys.path)
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != SRC_DIR.resolve()]
    sys.modules.pop("multihop_eval", None)
    try:
        _load_main_module()
        import multihop_eval  # noqa: F401 — import must succeed after main sets up the path

        assert Path(multihop_eval.__file__).resolve().parent == (SRC_DIR / "multihop_eval").resolve()
    finally:
        sys.path[:] = original


def test_main_does_not_duplicate_src_on_path() -> None:
    """Idempotent: importing twice must not add ``src`` to ``sys.path`` twice."""
    original = list(sys.path)
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != SRC_DIR.resolve()]
    try:
        _load_main_module()
        _load_main_module()
        resolved = [p for p in sys.path if Path(p).resolve() == SRC_DIR.resolve()]
        assert len(resolved) == 1
    finally:
        sys.path[:] = original
