"""Every widget on the RAG Eval page must have a `help=` tooltip.

Mirrors `test_ui_config_form_help.py` but targets `rag_eval_tab.py` and
`multi_system_compare.py`. Streamlit's input widgets accept a `help` kwarg
that renders the small "i" icon next to the label; we parse the source
file with `ast` and assert that every such widget call carries `help=`
with a non-empty string.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

UI_COMPONENTS = (
    Path(__file__).resolve().parents[2] / "src" / "multihop_eval" / "ui" / "components"
)
RAG_EVAL_TAB = UI_COMPONENTS / "rag_eval_tab.py"
MULTI_SYSTEM_COMPARE = UI_COMPONENTS / "multi_system_compare.py"

INPUT_WIDGETS: frozenset[str] = frozenset(
    {
        "text_input",
        "text_area",
        "number_input",
        "slider",
        "checkbox",
        "selectbox",
        "radio",
        "multiselect",
        "button",
        "download_button",
        "file_uploader",
    }
)

COLUMN_CONFIG_DESCRIPTORS: frozenset[str] = frozenset(
    {
        "TextColumn",
        "NumberColumn",
        "CheckboxColumn",
        "SelectboxColumn",
    }
)

# `st.metric(...)` accepts an optional `help=` — we don't require it everywhere
# (the metric label is usually self-explanatory) but if a `help=` is present it
# must be a real string, never empty / `None`. We enforce this only on metrics
# that *do* opt into a help kwarg, hence METRIC_OPTIONAL.
METRIC_OPTIONAL: frozenset[str] = frozenset({"metric"})
ALL_HELP_REQUIRED: frozenset[str] = INPUT_WIDGETS | COLUMN_CONFIG_DESCRIPTORS


def _attr_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _help_kwarg(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "help":
            return kw.value
    return None


def _safe_str_eval(node: ast.expr) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _collect_calls(path: Path, names: frozenset[str]) -> list[ast.Call]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (_attr_name(node.func) in names)
    ]


@pytest.fixture(scope="module")
def required_widget_calls() -> list[tuple[Path, ast.Call]]:
    calls: list[tuple[Path, ast.Call]] = []
    for path in (RAG_EVAL_TAB, MULTI_SYSTEM_COMPARE):
        for call in _collect_calls(path, ALL_HELP_REQUIRED):
            calls.append((path, call))
    assert calls, "Expected to find at least one widget call across the RAG-eval UI files."
    return calls


@pytest.fixture(scope="module")
def metric_calls_with_help() -> list[tuple[Path, ast.Call]]:
    out: list[tuple[Path, ast.Call]] = []
    for path in (RAG_EVAL_TAB, MULTI_SYSTEM_COMPARE):
        for call in _collect_calls(path, METRIC_OPTIONAL):
            if _help_kwarg(call) is not None:
                out.append((path, call))
    return out


def test_every_required_widget_has_help(required_widget_calls):
    missing: list[str] = []
    for path, call in required_widget_calls:
        name = _attr_name(call.func) or "<unknown>"
        if _help_kwarg(call) is None:
            label = "<dynamic>" if not call.args else (_safe_str_eval(call.args[0]) or "<dynamic>")
            missing.append(f"  {path.name}:{call.lineno} {name}({label!r})")
    assert not missing, "Widgets missing help=:\n" + "\n".join(missing)


def test_every_help_kwarg_is_a_meaningful_string(required_widget_calls, metric_calls_with_help):
    bad: list[str] = []
    for path, call in (*required_widget_calls, *metric_calls_with_help):
        help_node = _help_kwarg(call)
        if help_node is None:
            continue
        text = _safe_str_eval(help_node)
        name = _attr_name(call.func) or "<unknown>"
        if text is None:
            bad.append(f"  {path.name}:{call.lineno} {name} — help= is not a string literal.")
        elif not text.strip():
            bad.append(f"  {path.name}:{call.lineno} {name} — help= is empty.")
        elif len(text.strip()) < 12:
            bad.append(f"  {path.name}:{call.lineno} {name} — help= too short ({text!r}).")
    assert not bad, "Bad help= text:\n" + "\n".join(bad)


def test_no_emoji_in_help_text(required_widget_calls, metric_calls_with_help):
    bad: list[str] = []
    for path, call in (*required_widget_calls, *metric_calls_with_help):
        help_node = _help_kwarg(call)
        if help_node is None:
            continue
        text = _safe_str_eval(help_node)
        if text is None:
            continue
        for ch in text:
            if ord(ch) > 0xFFFF:
                bad.append(f"  {path.name}:{call.lineno}: '{ch}' in help= text.")
                break
    assert not bad, "Emoji in help= text:\n" + "\n".join(bad)
