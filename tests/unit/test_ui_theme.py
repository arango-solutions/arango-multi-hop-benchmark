"""Tests for `multihop_eval.ui.theme` — avocado palette + Altair theme.

Pins palette constants to the documented hex codes from the published
avocado-green palette so accidental drift (typo'd hex, dropped digit,
swapped channel) shows up as a red test rather than a subtle UI bug.
"""

from __future__ import annotations

import re

import altair as alt
import pytest

from multihop_eval.ui import theme

# Hex codes copied verbatim from the published avocado-green palette
# (https://www.figma.com/colors/avocado-green/). Any drift here means
# someone changed a constant without updating its source-of-truth note.
_DOCUMENTED_HEX = {
    "AVOCADO_PRIMARY": "#568203",
    "AVOCADO_SHADE_DEEP": "#1D2B01",
    "AVOCADO_SHADE_MID": "#395702",
    "AVOCADO_TINT_BRIGHT": "#82A903",
    "AVOCADO_TINT_LIGHTEST": "#DAFD9A",
    "AVOCADO_OLIVE": "#697F03",
    "AVOCADO_MOSS": "#89B34E",
    "AVOCADO_EARTH": "#A98403",
    "AVOCADO_TEAL": "#4EABB3",
    "AVOCADO_TAUPE": "#54463A",
}

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@pytest.mark.parametrize("name,expected", sorted(_DOCUMENTED_HEX.items()))
def test_palette_constants_match_published_hex_codes(name: str, expected: str) -> None:
    assert getattr(theme, name) == expected


def test_surface_muted_is_valid_hex() -> None:
    # SURFACE_MUTED is intentionally derived (not from the published palette);
    # we only assert it's a well-formed 6-digit hex code so the Streamlit
    # config.toml parser doesn't choke on it.
    assert _HEX_RE.match(theme.SURFACE_MUTED), theme.SURFACE_MUTED


def test_categorical_palette_is_non_empty_and_unique() -> None:
    palette = theme.CATEGORICAL_PALETTE
    assert len(palette) >= 4, "need enough hues for typical multi-system charts"
    assert len(set(palette)) == len(palette), "palette entries must be unique"
    for hex_code in palette:
        assert _HEX_RE.match(hex_code), hex_code


def test_categorical_palette_anchors_on_brand_primary() -> None:
    # Convention: the first colour is the primary brand colour so single-
    # series charts (and the first system in a comparison) look on-brand.
    assert theme.CATEGORICAL_PALETTE[0] == theme.AVOCADO_PRIMARY


def test_apply_altair_theme_registers_and_enables_avocado() -> None:
    # Bounce off another built-in theme first to prove `enable` flips it.
    alt.theme.enable("default")
    theme.apply_altair_theme()
    assert alt.theme.active == theme.ALTAIR_THEME_NAME

    config = alt.theme.get()()
    assert (
        config["config"]["range"]["category"][0] == theme.AVOCADO_PRIMARY
    ), "category range should lead with the brand primary"


def test_apply_altair_theme_is_idempotent() -> None:
    theme.apply_altair_theme()
    theme.apply_altair_theme()
    assert alt.theme.active == theme.ALTAIR_THEME_NAME


def test_avocado_color_scale_carries_full_categorical_palette() -> None:
    scale = theme.avocado_color_scale()
    # Altair's Scale stores its `range` argument as-is on the `.range` attr.
    assert list(scale.range) == list(theme.CATEGORICAL_PALETTE)
