"""Avocado-themed palette + Altair theme for the Arango multi-hop eval UI.

All colour constants come from the published avocado-green palette
(https://www.figma.com/colors/avocado-green/). The few derived values
(`SURFACE_MUTED`, etc.) are flagged in their docstring; the rest are
verbatim hex codes from the page so the look stays consistent across
Streamlit's `.streamlit/config.toml`, Altair charts, and any future
inline-CSS polish.

To recolour the app, change the constants here and the matching values
in `.streamlit/config.toml` — they are kept deliberately in sync.
"""

from __future__ import annotations

import altair as alt

# --- Core avocado palette (verbatim from the published palette) -------------

AVOCADO_PRIMARY = "#568203"  # Avocado green — the brand anchor.
AVOCADO_SHADE_DEEP = "#1D2B01"  # Shade #7 — body text on light backgrounds.
AVOCADO_SHADE_MID = "#395702"  # Shade #4 — hover/active emphasis.
AVOCADO_TINT_BRIGHT = "#82A903"  # Brighter on-brand green for secondary accents.
AVOCADO_TINT_LIGHTEST = "#DAFD9A"  # Tint #8 — playful highlight, *not* a body bg.
AVOCADO_OLIVE = "#697F03"  # "Vibrant Terra" olive — pairs with the primary.
AVOCADO_MOSS = "#89B34E"  # "Verdant Deep" moss — soft fourth-series green.
AVOCADO_EARTH = "#A98403"  # Earthy gold from "Vibrant Terra".
AVOCADO_TEAL = "#4EABB3"  # "Verdant Deep" teal — sits well next to greens.
AVOCADO_TAUPE = "#54463A"  # Recommended neutral companion (per the page).

# --- Derived surface colour --------------------------------------------------
#
# `SURFACE_MUTED` is `AVOCADO_TINT_LIGHTEST` mixed ~50% with white. It exists
# because the documented lightest tint (#DAFD9A) is too vivid for large
# secondary surfaces (sidebars, info banners). Keep this in lockstep with
# `.streamlit/config.toml` -> `secondaryBackgroundColor`.
SURFACE_MUTED = "#F0F7DD"

# --- Categorical chart palette ----------------------------------------------
#
# Ordered for maximum hue-separation so adjacent series stay legible.
# Used by Altair via `apply_altair_theme()` and explicitly by chart code
# that wants to opt-in regardless of theme registration order.
CATEGORICAL_PALETTE: tuple[str, ...] = (
    AVOCADO_PRIMARY,
    AVOCADO_EARTH,
    AVOCADO_TEAL,
    AVOCADO_OLIVE,
    AVOCADO_TINT_BRIGHT,
    AVOCADO_SHADE_MID,
    AVOCADO_TAUPE,
    AVOCADO_MOSS,
)

ALTAIR_THEME_NAME = "avocado"


def _avocado_altair_theme() -> dict:
    """Return the Altair theme config dict for the avocado palette.

    Kept as a function so registration can be deferred (Altair requires a
    callable) and so tests can introspect the config without touching
    Altair's global registry.
    """
    return {
        "config": {
            "background": "white",
            "title": {"color": AVOCADO_SHADE_DEEP, "fontSize": 14},
            "axis": {
                "labelColor": AVOCADO_SHADE_DEEP,
                "titleColor": AVOCADO_SHADE_DEEP,
                "gridColor": SURFACE_MUTED,
                "domainColor": AVOCADO_SHADE_DEEP,
                "tickColor": AVOCADO_SHADE_DEEP,
            },
            "legend": {
                "labelColor": AVOCADO_SHADE_DEEP,
                "titleColor": AVOCADO_SHADE_DEEP,
            },
            "range": {
                "category": list(CATEGORICAL_PALETTE),
                "ordinal": [
                    AVOCADO_TINT_LIGHTEST,
                    AVOCADO_TINT_BRIGHT,
                    AVOCADO_PRIMARY,
                    AVOCADO_SHADE_MID,
                    AVOCADO_SHADE_DEEP,
                ],
            },
            "mark": {"color": AVOCADO_PRIMARY},
            "bar": {"color": AVOCADO_PRIMARY},
            "line": {"color": AVOCADO_PRIMARY},
            "point": {"color": AVOCADO_PRIMARY, "filled": True},
        }
    }


def apply_altair_theme() -> None:
    """Register and enable the avocado Altair theme.

    Safe to call repeatedly: `alt.theme.register` overwrites the existing
    entry and `alt.theme.enable` simply flips the active theme name. Call
    once at app startup before any chart is rendered.

    Uses the modern `alt.theme` (singular) API introduced in altair 5.5;
    `alt.themes` (plural) is deprecated and will be removed.
    """
    alt.theme.register(ALTAIR_THEME_NAME, enable=True)(_avocado_altair_theme)


def avocado_color_scale() -> alt.Scale:
    """Return an `alt.Scale` pre-loaded with the categorical avocado palette.

    Use this on `alt.Color(..., scale=avocado_color_scale())` when a chart
    must look on-brand even if the global Altair theme hasn't been
    registered yet (e.g. in a notebook or a test).
    """
    return alt.Scale(range=list(CATEGORICAL_PALETTE))
