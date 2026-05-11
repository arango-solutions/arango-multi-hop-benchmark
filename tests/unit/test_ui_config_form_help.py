"""Every widget on the Configure page must have a `help=` tooltip.

This is a regression guard, not a behavioural test. Streamlit's widgets accept
a `help` kwarg that renders the small "ⓘ" icon next to the label; we parse the
source file with `ast` and assert that:

  1. Every call to a known input widget has a `help` kwarg.
  2. Every such `help` kwarg evaluates to a non-empty string literal.

If anyone adds a new widget to `config_form.py` without a tooltip, this test
fails immediately — which is the whole point.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CONFIG_FORM = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "multihop_eval"
    / "ui"
    / "components"
    / "config_form.py"
)

# Streamlit widgets that support `help=` and that we use on the Configure page.
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
    }
)

# `column_config.*` descriptors used inside `data_editor`'s `column_config={...}`.
# These also accept `help` and surface a tooltip next to the column header.
COLUMN_CONFIG_DESCRIPTORS: frozenset[str] = frozenset(
    {
        "TextColumn",
        "NumberColumn",
        "CheckboxColumn",
        "SelectboxColumn",
    }
)

ALL_HELP_REQUIRED: frozenset[str] = INPUT_WIDGETS | COLUMN_CONFIG_DESCRIPTORS


def _attr_name(func: ast.AST) -> str | None:
    """Return the trailing attribute name of a call's func, e.g. `text_input`
    for `cols[0].text_input(...)` or `st.column_config.TextColumn(...)`.
    """
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _help_kwarg_value(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "help":
            return kw.value
    return None


def _safe_str_eval(node: ast.expr) -> str | None:
    """Best-effort string extraction. Returns None if the expression isn't a
    plain string literal (possibly parenthesised / implicitly concatenated)."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _widget_calls(tree: ast.AST) -> list[ast.Call]:
    """Find every Call whose function is an attribute access ending in a known
    widget name (e.g. `cols[0].text_input(...)`, `st.column_config.TextColumn(...)`).
    """
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _attr_name(node.func)
        if name is None:
            continue
        if name in ALL_HELP_REQUIRED:
            out.append(node)
    return out


@pytest.fixture(scope="module")
def widget_calls() -> list[ast.Call]:
    source = CONFIG_FORM.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONFIG_FORM))
    calls = _widget_calls(tree)
    assert calls, "Expected to find at least one widget call in config_form.py."
    return calls


def test_every_widget_has_a_help_kwarg(widget_calls):
    """Spec: every input widget on the Configure page must carry `help=...`."""
    missing: list[str] = []
    for call in widget_calls:
        name = _attr_name(call.func) or "<unknown>"
        # First positional arg is the label — surface it for a useful error.
        if call.args:
            label_node = call.args[0]
            label = _safe_str_eval(label_node) or "<dynamic label>"
        else:
            label = "<no positional label>"
        if _help_kwarg_value(call) is None:
            missing.append(f"  • {name}({label!r}) at line {call.lineno}")
    assert not missing, (
        "The following widgets are missing a `help=` tooltip on the "
        "Configure page:\n" + "\n".join(missing)
    )


def test_every_help_kwarg_is_a_nonempty_string(widget_calls):
    """Spec: `help=` must be a real, non-empty string — not None, not empty."""
    bad: list[str] = []
    for call in widget_calls:
        name = _attr_name(call.func) or "<unknown>"
        help_node = _help_kwarg_value(call)
        if help_node is None:
            continue  # caught by the test above
        help_text = _safe_str_eval(help_node)
        if help_text is None:
            bad.append(
                f"  • {name}(...) at line {call.lineno} — help= is not a string literal."
            )
        elif not help_text.strip():
            bad.append(f"  • {name}(...) at line {call.lineno} — help= is empty.")
        elif len(help_text.strip()) < 12:
            bad.append(
                f"  • {name}(...) at line {call.lineno} — help= is suspiciously short "
                f"({help_text!r})."
            )
    assert not bad, "Bad help= tooltips:\n" + "\n".join(bad)


def test_config_form_source_uses_no_emoji_in_help_text(widget_calls):
    """The help tooltips are read aloud by screen readers; avoid emoji noise."""
    bad: list[str] = []
    for call in widget_calls:
        help_node = _help_kwarg_value(call)
        if help_node is None:
            continue
        text = _safe_str_eval(help_node)
        if text is None:
            continue
        for ch in text:
            # Anything in the supplementary planes is almost certainly an emoji.
            if ord(ch) > 0xFFFF:
                bad.append(f"  • line {call.lineno}: '{ch}' in help= text.")
                break
    assert not bad, "help= text should not contain emoji:\n" + "\n".join(bad)
