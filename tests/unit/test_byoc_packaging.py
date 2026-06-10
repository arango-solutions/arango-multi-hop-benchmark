"""Tests for the Arango BYOC packaging artefacts.

These guard the manual-packaging path that sidesteps ServiceMaker's
diff-and-move ``prepareproject.sh`` (which drops compiled native extensions
like ``pydantic_core._pydantic_core`` and causes ``ModuleNotFoundError`` at
runtime).

We assert two invariants:
  * ``requirements.txt`` stays mechanically in sync with
    ``pyproject.toml``'s ``[project].dependencies`` (so the BYOC venv installs
    exactly the declared deps).
  * The BYOC build hook / entrypoint files exist and are wired correctly.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync-requirements.sh"
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "prepareproject.sh"
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package-arango-manual.sh"
ENTRYPOINT = REPO_ROOT / "entrypoint"
DOCKERFILE_BYOC = REPO_ROOT / "Dockerfile.byoc"


def _declared_dependencies() -> list[str]:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return list(data.get("project", {}).get("dependencies", []))


def test_requirements_txt_lists_every_declared_dependency() -> None:
    """requirements.txt must contain each pyproject [project].dependencies entry."""
    assert REQUIREMENTS.is_file(), "requirements.txt is missing; run scripts/sync-requirements.sh"
    body_lines = {
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for dep in _declared_dependencies():
        assert dep in body_lines, f"{dep!r} declared in pyproject.toml but missing from requirements.txt"


def test_requirements_txt_has_no_undeclared_dependencies() -> None:
    """requirements.txt must not drift ahead of pyproject.toml."""
    declared = set(_declared_dependencies())
    body_lines = {
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    extra = body_lines - declared
    assert not extra, f"requirements.txt has entries not in pyproject.toml: {sorted(extra)}"


def test_sync_requirements_check_passes() -> None:
    """The --check mode of the sync script must report in-sync state."""
    result = subprocess.run(  # noqa: S603 — fixed args, repo-local script
        ["bash", str(SYNC_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"sync-requirements --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_byoc_scripts_are_executable_shell() -> None:
    for script in (SYNC_SCRIPT, PREPARE_SCRIPT, PACKAGE_SCRIPT):
        assert script.is_file(), f"missing BYOC script: {script}"
        first_line = script.read_text().splitlines()[0]
        assert first_line.startswith("#!"), f"{script.name} lacks a shebang"


def test_prepareproject_builds_complete_venv_not_diff_move() -> None:
    """The build hook must install into /project/the_venv directly (not diff-and-move).

    Regression guard for the ``pydantic_core._pydantic_core`` failure: a real
    ``pip install`` into the target venv keeps compiled extensions intact.
    """
    text = PREPARE_SCRIPT.read_text()
    assert "pip install -r" in text
    assert "/project/the_venv" in text
    # Must NOT reuse ServiceMaker's fragile relocation strategy.
    assert "newfiles" not in text
    assert "sums_sha256" not in text


def test_prepareproject_uses_uv_for_arango_base_image() -> None:
    """arangodb/py13base has no system python3 — the hook must build via uv."""
    text = PREPARE_SCRIPT.read_text()
    assert "uv venv" in text, "hook must create the venv with uv (no system python3 in base image)"
    assert "/home/user/.local/bin/env" in text, "hook must source uv onto PATH for 'user'"


def test_dockerfile_byoc_builds_venv_in_base_image() -> None:
    """The packaging Dockerfile must build the venv inside the Linux base image.

    Building the venv in the base image (not copying a macOS .venv) is what
    keeps compiled extensions architecture-correct.
    """
    assert DOCKERFILE_BYOC.is_file(), "Dockerfile.byoc is missing"
    text = DOCKERFILE_BYOC.read_text()
    assert "arangodb/py13base" in text
    assert "prepareproject.sh" in text
    # The venv must be produced as part of the image build.
    assert "RUN /project/scripts/prepareproject.sh" in text


def test_package_script_extracts_the_venv_into_tarball() -> None:
    """The packaging script must ship /project/the_venv (deps), not source only."""
    text = PACKAGE_SCRIPT.read_text()
    assert "Dockerfile.byoc" in text
    assert "docker build" in text
    assert "/project" in text


def test_entrypoint_targets_main_py() -> None:
    assert ENTRYPOINT.is_file(), "root entrypoint file is missing"
    first_token = ENTRYPOINT.read_text().split()[0]
    assert first_token == "main.py", f"entrypoint first token must be main.py, got {first_token!r}"
    assert (REPO_ROOT / first_token).is_file()


def test_sync_requirements_check_detects_drift(tmp_path: Path) -> None:
    """If requirements.txt drifts, --check must fail (would have caught regressions)."""
    backup = REQUIREMENTS.read_text()
    try:
        REQUIREMENTS.write_text(backup + "\nnot-a-real-dep==9.9.9\n")
        result = subprocess.run(  # noqa: S603 — fixed args, repo-local script
            ["bash", str(SYNC_SCRIPT), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0
    finally:
        REQUIREMENTS.write_text(backup)


if __name__ == "__main__":
    sys.exit(0)
