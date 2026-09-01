"""Integrity checks for the shipped ``static/`` UI tree.

Two BYOC failure modes are guarded here, both of which only surface in a
browser against a deployed service and are therefore easy to ship broken:

* A **dangling reference** — index.html or an ES module imports a file that
  is not in the archive, so the UI renders a blank page.
* An **absolute URL** — ``href="/style.css"`` or ``import "/js/app.js"``
  escapes the ``/_service/uds/_db/<db>/<app>/`` prefix and hits the Arango
  coordinator instead of the service. This is the documented top failure in
  the arango-byoc skill's known-failures table.

Every referenced asset is also fetched through the real ASGI app, so the
routing and the file tree are verified together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from multihop_eval.web.service import app as real_app

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "static"

# href="…" / src="…" in HTML, excluding in-page anchors and external URLs.
_HTML_REF = re.compile(r"""(?:href|src)\s*=\s*["']([^"'#]+)["']""")
# Static `import … from "./x.js"` and side-effect `import "./x.js"`.
_JS_IMPORT = re.compile(r"""\bimport\s+(?:[^"';]*?\bfrom\s*)?["']([^"']+)["']""")

_EXTERNAL = ("http://", "https://", "//", "data:", "mailto:")

# Patterns that would make the browser resolve against the domain root rather
# than the service prefix.
_ABSOLUTE_URL_PATTERNS = {
    'href="/': re.compile(r"""href\s*=\s*["']/"""),
    'src="/': re.compile(r"""src\s*=\s*["']/"""),
    'import from "/': re.compile(r"""\bimport\s+[^"';]*?\bfrom\s*["']/"""),
    'import "/': re.compile(r"""\bimport\s*["']/"""),
    'fetch("/': re.compile(r"""\bfetch\s*\(\s*["']/"""),
    "css url(/": re.compile(r"""url\(\s*["']?/"""),
}


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_comments(text: str, suffix: str) -> str:
    """Drop comments so prose describing a bad pattern isn't flagged as one.

    Only whole-line ``//`` comments are removed, never trailing ones, so a
    ``//`` inside a string literal can't truncate real code.
    """
    if suffix == ".html":
        return _HTML_COMMENT.sub("", text)
    text = _BLOCK_COMMENT.sub("", text)
    if suffix == ".css":
        return text
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(("//", "*"))
    )


def _code(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"), path.suffix)


def _static_files(suffix: str) -> list[Path]:
    return sorted(STATIC_DIR.rglob(f"*{suffix}"))


def _relative_refs(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [m for m in pattern.findall(text) if not m.startswith(_EXTERNAL)]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(real_app)


def test_static_tree_exists() -> None:
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "css" / "styles.css").is_file()
    assert (STATIC_DIR / "js" / "app.js").is_file()


def test_index_references_resolve() -> None:
    index = STATIC_DIR / "index.html"
    refs = _relative_refs(index.read_text(encoding="utf-8"), _HTML_REF)
    assert refs, "index.html references no assets at all"
    for ref in refs:
        assert (STATIC_DIR / ref).is_file(), f"index.html references missing file: {ref}"


def test_every_js_import_resolves() -> None:
    """Walk the module graph: a typo'd import renders a blank page."""
    js_files = _static_files(".js")
    assert js_files, "no JS modules found under static/"
    for source in js_files:
        for ref in _relative_refs(_code(source), _JS_IMPORT):
            target = (source.parent / ref).resolve()
            assert target.is_file(), f"{source.relative_to(STATIC_DIR)} imports missing {ref}"
            assert STATIC_DIR.resolve() in target.parents, (
                f"{source.relative_to(STATIC_DIR)} imports outside static/: {ref}"
            )


def test_app_js_is_reachable_from_index() -> None:
    """The entry module must be the one index.html actually loads."""
    index_text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'type="module"' in index_text
    assert "js/app.js" in index_text


@pytest.mark.parametrize(
    ("label", "pattern"), sorted((k, v) for k, v in _ABSOLUTE_URL_PATTERNS.items())
)
def test_no_absolute_urls_anywhere_in_static(label: str, pattern: re.Pattern[str]) -> None:
    offenders = [
        f"{path.relative_to(STATIC_DIR)}: {pattern.search(text).group(0)!r}"
        for path in STATIC_DIR.rglob("*")
        if path.is_file() and path.suffix in {".html", ".js", ".css"}
        for text in [_code(path)]
        if pattern.search(text)
    ]
    assert not offenders, (
        f"absolute URL ({label}) breaks the BYOC service prefix:\n  " + "\n  ".join(offenders)
    )


def test_api_calls_go_through_api_base() -> None:
    """Every fetch must be prefixed with apiBase(), never rooted at /."""
    api_js = _code(STATIC_DIR / "js" / "api.js")
    fetch_calls = re.findall(r"\bfetch\(([^\n]*)", api_js)
    assert fetch_calls, "api.js makes no fetch calls"
    for call in fetch_calls:
        assert "apiBase()" in call, f"fetch not rooted at apiBase(): {call.strip()}"


# ---------------------------------------------------------------------------
# The same assets, fetched through the real app
# ---------------------------------------------------------------------------


def _served_paths() -> list[str]:
    paths = []
    for path in sorted(STATIC_DIR.rglob("*")):
        if path.is_file() and path.name != "index.html":
            paths.append(path.relative_to(STATIC_DIR).as_posix())
    return paths


@pytest.mark.parametrize("relative", _served_paths())
def test_every_static_file_is_served_at_the_service_root(
    client: TestClient, relative: str
) -> None:
    """Relative URLs resolve to the service root when the UI is mounted at /."""
    resp = client.get(f"/{relative}")
    assert resp.status_code == 200, relative
    assert resp.content == (STATIC_DIR / relative).read_bytes(), relative


@pytest.mark.parametrize("prefix", ["/ui", "/frontend"])
def test_entry_module_is_served_under_each_prefix(client: TestClient, prefix: str) -> None:
    resp = client.get(f"{prefix}/js/app.js")
    assert resp.status_code == 200
    assert resp.content == (STATIC_DIR / "js" / "app.js").read_bytes()
