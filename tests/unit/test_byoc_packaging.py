"""Tests for the Arango BYOC packaging path.

Packaging bugs only surface as a dead container in the cluster, so the
invariants that have actually bitten this service are pinned here:

* ``main.py`` must put the vendored ``the_venv`` on ``sys.path`` *before* any
  third-party import, or py12base (which has no pip and no site-packages of
  ours) dies with ``ModuleNotFoundError: pydantic_core``.
* The packer must target cp312 / manylinux_2_28. The skill's default
  manylinux_2_17 has no cp312 wheels for numpy/pandas/rapidfuzz, so uv builds
  them from source and silently emits macOS binaries.
* The staging directory must not collide with the scratch directory pack.sh
  derives from the output path, or the packer deletes its own input.

The archive itself is only built when ``BYOC_PACK=1`` — it downloads ~170 MB
of wheels, which is too slow for the default suite.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package_byoc.sh"
SKILL_PACK = REPO_ROOT / ".cursor" / "skills" / "arango-byoc" / "scripts" / "pack.sh"
MAIN_PY = REPO_ROOT / "main.py"

PYTHON_VERSION = "3.12"
NAME = "multihop-eval"


# ---------------------------------------------------------------------------
# main.py — the runtime contract
# ---------------------------------------------------------------------------


def _load_main():
    """Import main.py without leaving its sys.path edits behind."""
    original = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("_byoc_main", MAIN_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original


def test_bundled_site_packages_are_prepended_before_third_party_imports() -> None:
    """A top-level `import uvicorn` would run before the venv is on the path."""
    source = MAIN_PY.read_text(encoding="utf-8")
    setup_at = source.index("_prepend_bundled_site_packages()\n\n")
    uvicorn_at = source.index("import uvicorn")
    assert setup_at < uvicorn_at, "uvicorn is imported before the_venv is on sys.path"


def test_prepend_puts_a_discovered_venv_first(tmp_path: Path, monkeypatch) -> None:
    module = _load_main()
    site_packages = tmp_path / "the_venv" / f"lib/python{PYTHON_VERSION}" / "site-packages"
    site_packages.mkdir(parents=True)
    # The archive layout is /project/the_venv beside /project/<name>/main.py.
    monkeypatch.setattr(module, "_DIR", tmp_path / NAME)
    monkeypatch.setattr(sys, "path", ["/somewhere/else"])

    module._prepend_bundled_site_packages()

    assert sys.path[0] == str(site_packages.resolve())


def test_prepend_is_a_noop_without_a_bundled_venv(tmp_path: Path, monkeypatch) -> None:
    module = _load_main()
    monkeypatch.setattr(module, "_DIR", tmp_path / NAME)
    monkeypatch.setattr(sys, "path", ["/somewhere/else"])

    module._prepend_bundled_site_packages()

    assert sys.path == ["/somewhere/else"]


def test_prepend_does_not_duplicate_an_existing_entry(tmp_path: Path, monkeypatch) -> None:
    module = _load_main()
    site_packages = tmp_path / "the_venv" / f"lib/python{PYTHON_VERSION}" / "site-packages"
    site_packages.mkdir(parents=True)
    resolved = str(site_packages.resolve())
    monkeypatch.setattr(module, "_DIR", tmp_path / NAME)
    monkeypatch.setattr(sys, "path", ["/somewhere/else", resolved])

    module._prepend_bundled_site_packages()

    assert sys.path.count(resolved) == 1
    assert sys.path[0] == resolved


def test_server_binds_the_byoc_socket() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert '"PORT", "8000"' in source
    assert '"HOST", "0.0.0.0"' in source
    assert "proxy_headers=True" in source


# ---------------------------------------------------------------------------
# package_byoc.sh — the packaging contract
# ---------------------------------------------------------------------------


def test_package_script_is_executable_shell() -> None:
    assert PACKAGE_SCRIPT.is_file(), "scripts/package_byoc.sh is missing"
    assert os.access(PACKAGE_SCRIPT, os.X_OK), "package_byoc.sh is not executable"
    assert PACKAGE_SCRIPT.read_text(encoding="utf-8").startswith("#!")


def test_package_script_delegates_to_the_skill_packer() -> None:
    """The skill says to execute pack.sh, not reimplement it."""
    text = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    assert "arango-byoc/scripts/pack.sh" in text
    assert "tar czf" not in text, "packaging must go through pack.sh, not raw tar"
    assert SKILL_PACK.is_file(), "the arango-byoc skill packer is missing from this repo"


def test_package_script_targets_py12_and_a_glibc_with_cp312_wheels() -> None:
    """Regression: manylinux_2_17 has no cp312 numpy/pandas wheels."""
    text = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    assert f'BYOC_PYTHON_VERSION:-{PYTHON_VERSION}' in text
    assert "manylinux_2_28" in text
    assert "BYOC_PLATFORM:-x86_64-manylinux_2_28" in text


def test_staging_dir_cannot_collide_with_the_packer_scratch_dir() -> None:
    """pack.sh rm -rf's "$(dirname "$OUT")/$NAME" before copying the source.

    Staging into that exact path wipes the input and the pack fails with a
    confusing "pyproject.toml missing".
    """
    text = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    assert "dist/byoc-src" in text
    assert 'OUT:-${REPO_ROOT}/dist/${NAME}.tar.gz' in text


def _copy_commands() -> list[str]:
    """The `cp` lines of the staging step, ignoring comments."""
    return [
        line.strip()
        for line in PACKAGE_SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("cp ")
    ]


def test_package_script_stages_only_what_the_service_needs() -> None:
    copies = _copy_commands()
    staged = " ".join(copies)
    assert "main.py" in staged
    assert "pyproject.toml" in staged
    assert "src" in staged
    assert "static" in staged
    # Never the test suite, the lockfile, or a secrets file.
    for forbidden in ("tests", "uv.lock", ".env", ".git"):
        assert forbidden not in staged, f"package_byoc.sh stages {forbidden}"
    assert "refusing to package a .env file" in PACKAGE_SCRIPT.read_text(encoding="utf-8")


def test_package_script_verifies_the_archive_it_produced() -> None:
    """A silently-wrong archive is the failure mode; the packer must self-check."""
    text = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    for expected in ("^entrypoint$", "site-packages/fastapi/", "static/index.html", "LIBARCHIVE"):
        assert expected in text, f"package_byoc.sh does not check for {expected}"


# ---------------------------------------------------------------------------
# The real archive (opt-in: BYOC_PACK=1)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("BYOC_PACK") != "1",
    reason="set BYOC_PACK=1 to build the archive (downloads ~170 MB of wheels)",
)
def test_built_archive_has_the_layout_py12base_expects(tmp_path: Path) -> None:
    out = tmp_path / "multihop-eval.tar.gz"
    result = subprocess.run(  # noqa: S603 — fixed args, repo-local script
        ["bash", str(PACKAGE_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "OUT": str(out)},
    )
    assert result.returncode == 0, f"pack failed:\n{result.stdout}\n{result.stderr}"

    with tarfile.open(out) as tar:
        names = tar.getnames()
        entrypoint = tar.extractfile("entrypoint").read().decode().strip()

    assert entrypoint == f"/project/{NAME}/main.py"
    assert f"{NAME}/main.py" in names
    assert f"{NAME}/static/index.html" in names
    assert f"{NAME}/static/js/app.js" in names
    assert f"{NAME}/src/multihop_eval/web/service.py" in names
    assert any(
        n.startswith(f"the_venv/lib/python{PYTHON_VERSION}/site-packages/fastapi/") for n in names
    )
    assert not any(".env" in n for n in names)
    assert not any("LIBARCHIVE" in n for n in names)
    assert not any(n.startswith(f"{NAME}/tests") for n in names)
